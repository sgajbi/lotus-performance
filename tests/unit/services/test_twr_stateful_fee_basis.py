from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from adapters.api_adapter import create_engine_config
from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.models.requests import DailyInputData, PerformanceRequest
from app.models.returns_series import ResolvedWindow
from app.models.twr_requests import TWRInputMode, TWRResolvedExecutionRequest
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.services import returns_series_service, twr_service, workspace_summary_service
from app.services.calculation_engine_version import CALCULATION_ENGINE_VERSION
from app.services.reproducibility_service import generate_value_fingerprint
from app.services.twr_calculation_service import build_resolved_twr_identity_payload
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points
from app.workers import compute_executor_worker
from common.enums import Frequency
from engine.config import EndingValueBasis

DAY = date(2026, 3, 12)


@pytest.mark.parametrize("retained_basis", [None, "FEE_EXCLUSIVE", "AFTER_FEES"])
@pytest.mark.parametrize("fee", ["-10", "10"])
@pytest.mark.parametrize("metric_basis", ["NET", "GROSS"])
@pytest.mark.parametrize("precision_mode", ["FLOAT64", "DECIMAL_STRICT"])
def test_persisted_twr_worker_executes_retained_basis(monkeypatch, retained_basis, fee, metric_basis, precision_mode):
    request = _performance_request(
        [{"perf_date": DAY.isoformat(), "begin_mv": "1000", "end_mv": "1090", "mgmt_fees": fee}],
        metric_basis,
        precision_mode,
    )
    payload = {"portfolio": request.model_dump(mode="json"), "benchmark": None}
    if retained_basis is not None:
        payload["ending_value_basis"] = retained_basis
    artifact = TWRResolvedExecutionRequest.model_validate(payload)
    expected_identity = generate_value_fingerprint(artifact, CALCULATION_ENGINE_VERSION)
    observed = []
    monkeypatch.setattr(twr_service.execution_registry, "start_stage", lambda *args: None)
    monkeypatch.setattr(twr_service, "_assemble_completed_twr_response", lambda **kwargs: kwargs)
    context = SimpleNamespace(
        settings=SimpleNamespace(CALCULATION_ENGINE_VERSION=CALCULATION_ENGINE_VERSION),
        execution_store=SimpleNamespace(update_execution_identity=lambda *args, **kwargs: observed.append(kwargs)),
        twr_calculator=twr_service.calculate_twr_response,
    )
    result = compute_executor_worker._execute_twr_job(
        SimpleNamespace(
            request_payload={"resolved_request": payload, "source_input_mode": "stateful"},
            calculation_id=request.calculation_id,
        ),
        context,
    )
    # Legacy payloads default to fee-exclusive; explicit retained semantics own execution.
    expected_pnl = Decimal("90")
    if artifact.ending_value_basis == EndingValueBasis.FEE_EXCLUSIVE and metric_basis == "NET":
        expected_pnl += Decimal(fee)
    elif artifact.ending_value_basis == EndingValueBasis.AFTER_FEES and metric_basis == "GROSS":
        expected_pnl -= Decimal(fee)
    assert result["calculation"].daily_results_df.iloc[0]["daily_ror"] == expected_pnl / 10
    evidence = (
        next(iter(result["results_by_period"].values())).portfolio.breakdowns[Frequency.DAILY][0].calculation_evidence
    )
    assert evidence.performance_pnl == expected_pnl
    assert evidence.management_fees == Decimal(fee)
    assert result["request_artifact_model"] == artifact
    assert observed == [{"input_fingerprint": expected_identity[0], "calculation_hash": expected_identity[1]}]


def _source_observation(*, fee: str, bod: str, eod: str) -> dict:
    return {
        "valuation_date": DAY.isoformat(),
        "beginning_market_value": "1000",
        "ending_market_value": str(Decimal("1100") + Decimal(bod) + Decimal(eod) + Decimal(fee)),
        "cash_flows": [
            {"amount": fee, "timing": "eod", "cash_flow_type": "FEE"},
            {"amount": bod, "timing": "bod", "cash_flow_type": "DEPOSIT"},
            {"amount": eod, "timing": "eod", "cash_flow_type": "WITHDRAWAL"},
        ],
    }


def _performance_request(points: list[dict], metric_basis: str, precision_mode: str) -> PerformanceRequest:
    return PerformanceRequest.model_validate(
        {
            "portfolio_id": "FEE_RECONCILIATION",
            "performance_start_date": DAY,
            "report_start_date": DAY,
            "report_end_date": DAY,
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "valuation_points": points,
            "metric_basis": metric_basis,
            "precision_mode": precision_mode,
        }
    )


@pytest.mark.parametrize("fee", ["-10", "10", "0"])
@pytest.mark.parametrize(("bod", "eod"), [("0", "0"), ("200", "-50")])
@pytest.mark.parametrize("metric_basis", ["NET", "GROSS"])
@pytest.mark.parametrize("precision_mode", ["FLOAT64", "DECIMAL_STRICT"])
def test_stateful_twr_matches_fee_exclusive_stateless_economics(fee, bod, eod, metric_basis, precision_mode):
    source = _source_observation(fee=fee, bod=bod, eod=eod)
    source_points = portfolio_timeseries_to_valuation_points(observations=[source])
    source_request = _performance_request(source_points, metric_basis, precision_mode)
    calculation = twr_service._run_twr_execution_calculation(
        performance_request=source_request, benchmark_request=None, input_mode=TWRInputMode.STATEFUL
    )
    stateful = calculation.daily_results_df
    explicit_points = [{**source_points[0], "end_mv": source_points[0]["end_mv"] - Decimal(fee)}]
    explicit_request = _performance_request(explicit_points, metric_basis, precision_mode)
    stateless = twr_service._run_twr_execution_calculation(
        performance_request=explicit_request, benchmark_request=None, input_mode=TWRInputMode.STATELESS
    ).daily_results_df
    expected_pnl = Decimal("100") + (Decimal(fee) if metric_basis == "NET" else Decimal("0"))
    expected_pct = expected_pnl / (Decimal("1000") + Decimal(bod)) * 100
    assert float(stateful.iloc[0]["daily_ror"]) == pytest.approx(float(expected_pct), abs=0.000001)
    assert stateful.iloc[0]["daily_ror"] == stateless.iloc[0]["daily_ror"]
    assert Decimal(str(stateful.iloc[0]["end_mv"])) == Decimal(source["ending_market_value"])
    assert source_points[0]["end_mv"] == Decimal(source["ending_market_value"])
    periods = twr_service._build_twr_execution_period_results(
        performance_request=source_request,
        calculation=calculation,
        benchmark_request=None,
        benchmark_input_mode=None,
        resolved_benchmark_id=None,
        benchmark_return_source=BenchmarkReturnSource.CALCULATED,
        input_mode=TWRInputMode.STATEFUL,
    )
    evidence = next(iter(periods.values())).portfolio.breakdowns[Frequency.DAILY][0].calculation_evidence
    assert evidence is not None
    assert evidence.performance_pnl == expected_pnl
    assert evidence.end_mv == Decimal(source["ending_market_value"])
    assert evidence.management_fees == Decimal(fee)
    assert create_engine_config(explicit_request, DAY, DAY).ending_value_basis == EndingValueBasis.FEE_EXCLUSIVE


@pytest.mark.parametrize("metric_basis", ["NET", "GROSS"])
@pytest.mark.parametrize("fee", ["-10", "10", "0"])
def test_returns_series_and_workspace_reconcile_to_core_after_fee_values(metric_basis, fee):
    source = _source_observation(fee=fee, bod="200", eod="-50")
    points = portfolio_timeseries_to_valuation_points(observations=[source])
    series = returns_series_service.daily_ror_from_portfolio_timeseries(
        observations=[source],
        performance_start_date=DAY,
        resolved_window=ResolvedWindow(start_date=DAY, end_date=DAY),
        metric_basis=metric_basis,
    )
    workspace_request = WorkspaceSummaryRequest.model_validate(
        {
            "portfolio_id": "FEE_RECONCILIATION",
            "input_mode": "stateful",
            "stateful_input": {},
            "performance_start_date": DAY,
            "report_start_date": DAY,
            "report_end_date": DAY,
            "periods": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        }
    )
    workspace = workspace_summary_service._calculate_workspace_twr_artifacts(
        request=workspace_request,
        valuation_points=[DailyInputData.model_validate(point) for point in points],
        performance_start_date=DAY,
        portfolio_base_currency="USD",
        metric_basis=metric_basis,
    ).daily_results_df
    expected = (Decimal("100") + (Decimal(fee) if metric_basis == "NET" else 0)) / Decimal("1200")
    assert float(series.iloc[0]["return_value"]) == pytest.approx(float(expected), abs=0.00000001)
    assert float(workspace.iloc[0]["daily_ror"]) / 100 == pytest.approx(float(expected), abs=0.00000001)
    economics = workspace_summary_service._build_economic_context(workspace)
    assert economics.end_market_value == Decimal(source["ending_market_value"])
    assert economics.fees == Decimal(fee)


def test_live_fee_day_regression_preserves_source_assets_and_net_return():
    source = {
        "valuation_date": DAY.isoformat(),
        "beginning_market_value": "1345366.377943536",
        "ending_market_value": "1345284.913033022",
        "cash_flows": [{"amount": "-275", "timing": "eod", "cash_flow_type": "FEE"}],
    }
    result = returns_series_service.daily_ror_from_portfolio_timeseries(
        observations=[source],
        performance_start_date=DAY,
        resolved_window=ResolvedWindow(start_date=DAY, end_date=DAY),
        metric_basis="NET",
    )
    # FLOAT64's six-decimal percentage rounding is retained at this boundary.
    assert result.iloc[0]["return_value"] == Decimal("-0.00006055")


def test_stateful_twr_restores_admitted_assets_after_report_window_slicing():
    points = [
        {"perf_date": "2026-03-11", "begin_mv": "1000", "end_mv": "1090", "mgmt_fees": "-10"},
        {"perf_date": DAY.isoformat(), "begin_mv": "1090", "end_mv": "1195", "mgmt_fees": "5"},
    ]
    request = _performance_request(points, "NET", "DECIMAL_STRICT")
    results = twr_service._run_twr_execution_calculation(
        performance_request=request, benchmark_request=None, input_mode=TWRInputMode.STATEFUL
    ).daily_results_df
    assert results["perf_date"].tolist() == [DAY]
    assert results.iloc[0]["end_mv"] == Decimal("1195")


def test_resolved_twr_identity_binds_fee_basis_without_rewriting_historical_requests():
    request = _performance_request(
        [{"perf_date": DAY.isoformat(), "begin_mv": "1000", "end_mv": "1090", "mgmt_fees": "-10"}],
        "NET",
        "DECIMAL_STRICT",
    )
    stateful = build_resolved_twr_identity_payload(
        performance_request=request, benchmark_request=None, input_mode=TWRInputMode.STATEFUL
    )
    stateless = build_resolved_twr_identity_payload(
        performance_request=request, benchmark_request=None, input_mode=TWRInputMode.STATELESS
    )
    assert stateful.ending_value_basis == EndingValueBasis.AFTER_FEES
    assert stateless.ending_value_basis == EndingValueBasis.FEE_EXCLUSIVE
    assert generate_value_fingerprint(stateful, CALCULATION_ENGINE_VERSION) != generate_value_fingerprint(
        stateless, CALCULATION_ENGINE_VERSION
    )
    historical_payload = {"portfolio": request.model_dump(mode="python"), "benchmark": None}
    assert type(stateful).model_validate(historical_payload).ending_value_basis == EndingValueBasis.FEE_EXCLUSIVE


@pytest.mark.parametrize("input_mode", [TWRInputMode.STATEFUL, TWRInputMode.STATELESS])
@pytest.mark.parametrize("metric_basis", ["NET", "GROSS"])
def test_raw_twr_worker_binds_same_basis_and_hash_as_sync_execution(monkeypatch, input_mode, metric_basis):
    request = _performance_request(
        [{"perf_date": DAY.isoformat(), "begin_mv": "1000", "end_mv": "1090", "mgmt_fees": "-10"}],
        metric_basis,
        "DECIMAL_STRICT",
    )

    async def resolve(analytics_request, *, settings):
        return SimpleNamespace(
            performance_request=request,
            benchmark_request=None,
            input_mode=analytics_request.input_mode,
            resolved_benchmark_id=None,
            benchmark_input_mode=None,
        )

    monkeypatch.setattr(compute_executor_worker, "resolve_twr_request", resolve)
    expected_artifact = build_resolved_twr_identity_payload(
        performance_request=request, benchmark_request=None, input_mode=input_mode
    )
    expected_identity = generate_value_fingerprint(expected_artifact, CALCULATION_ENGINE_VERSION)
    observed = []

    def calculate(performance_request, **metadata):
        artifact = metadata["request_artifact_model"]
        if input_mode == TWRInputMode.STATEFUL:
            assert artifact == expected_artifact
            assert (metadata["input_fingerprint"], metadata["calculation_hash"]) == expected_identity
        return twr_service._run_twr_execution_calculation(
            performance_request=performance_request, benchmark_request=None, input_mode=metadata["input_mode"]
        ).daily_results_df

    payload = request.model_dump(mode="json")
    payload["input_mode"] = input_mode.value
    if input_mode == TWRInputMode.STATEFUL:
        payload["stateful_input"] = {}
        payload.pop("valuation_points")
    context = SimpleNamespace(
        settings=SimpleNamespace(CALCULATION_ENGINE_VERSION=CALCULATION_ENGINE_VERSION),
        execution_store=SimpleNamespace(update_execution_identity=lambda *args, **kwargs: observed.append(kwargs)),
        twr_calculator=calculate,
    )
    result = compute_executor_worker._execute_twr_job(
        SimpleNamespace(request_payload=payload, calculation_id=request.calculation_id), context
    )
    expected_pnl = Decimal("90") if input_mode == TWRInputMode.STATEFUL else Decimal("80")
    if metric_basis == "GROSS":
        expected_pnl += 10
    assert result.iloc[0]["daily_ror"] == expected_pnl / 10
    if input_mode == TWRInputMode.STATEFUL:
        assert observed == [{"input_fingerprint": expected_identity[0], "calculation_hash": expected_identity[1]}]
    else:
        assert observed == []
