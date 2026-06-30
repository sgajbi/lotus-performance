from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from app.models.benchmark_analytics_requests import BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import DailyInputData
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.models.workspace_summary_responses import (
    WorkspaceBasisPair,
    WorkspaceEconomicContext,
    WorkspaceEconomicReturnSummary,
    WorkspaceMoneyWeightedReturnSummary,
    WorkspacePerformanceBlock,
    WorkspacePeriodSummaryResult,
    WorkspaceReturnSummary,
    WorkspaceReturnValue,
)
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY
from app.services.workspace_summary_service import (
    ResolvedWorkspaceBenchmarkInput,
    ResolvedWorkspacePortfolioInput,
    WorkspaceTWRArtifacts,
    _annualization_periods_and_elapsed_measure,
    _annualize_percentage,
    _annualize_return_value,
    _build_economic_context,
    _build_mwr_cash_flows,
    _build_stateful_workspace_benchmark_input,
    _build_stateful_workspace_portfolio_input,
    _build_stateless_workspace_benchmark_input,
    _build_stateless_workspace_portfolio_input,
    _build_workspace_active_block,
    _build_workspace_benchmark_and_active_blocks,
    _build_workspace_benchmark_daily_df,
    _build_workspace_performance_breakdowns,
    _build_workspace_period_summary_result,
    _build_workspace_period_twr_pair,
    _build_workspace_results_by_period,
    _build_workspace_summary_response,
    _date_from_boundary,
    _decimal_or_zero,
    _is_missing_decimal_value,
    _longest_workspace_period_days,
    _normalize_workspace_daily_results_df,
    _resolve_stateful_portfolio_start_date,
    _resolve_workspace_benchmark_input,
    _resolve_workspace_inputs,
    _resolve_workspace_portfolio_input,
    _sum_decimal_column,
    _workspace_observation_in_master_window,
    _workspace_summary_audit_counts,
    _workspace_summary_diagnostics,
    _workspace_summary_diagnostics_notes,
    _workspace_summary_meta,
    calculate_workspace_summary,
    calculate_workspace_summary_async,
    workspace_longest_requested_window_days,
)
from common.enums import Frequency
from core.envelope import Diagnostics
from core.errors import APIError
from core.workspace_periods import ResolvedWorkspacePeriod


def test_workspace_longest_requested_window_days_handles_stateful_since_inception_without_start_date():
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-06-30",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "SI", "frequencies": ["daily"]}],
        }
    )

    assert workspace_longest_requested_window_days(request) == 10_000


def test_workspace_longest_requested_window_days_ignores_stateless_requests():
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-06-30",
            "performance_start_date": "2026-01-01",
            "input_mode": "stateless",
            "stateless_input": {"valuation_points": [{"perf_date": "2026-06-30", "begin_mv": 100, "end_mv": 101}]},
            "periods": [{"period": "1M", "frequencies": ["daily"]}],
        }
    )

    assert workspace_longest_requested_window_days(request) == 0


def test_workspace_longest_requested_window_days_uses_report_start_fallback():
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_start_date": "2026-06-01",
            "report_end_date": "2026-06-30",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        }
    )

    assert workspace_longest_requested_window_days(request) == 29


def test_longest_workspace_period_days_returns_zero_for_empty_periods():
    assert _longest_workspace_period_days([]) == 0


def test_longest_workspace_period_days_uses_largest_resolved_window():
    assert (
        _longest_workspace_period_days(
            [
                ResolvedWorkspacePeriod(name="SHORT", start_date=date(2026, 6, 1), end_date=date(2026, 6, 5)),
                ResolvedWorkspacePeriod(name="LONG", start_date=date(2026, 5, 1), end_date=date(2026, 6, 30)),
            ]
        )
        == 60
    )


@pytest.mark.asyncio
async def test_workspace_summary_async_stateful_retrieval_uses_longest_requested_window(mocker):
    captured: dict[str, object] = {}
    lineage_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.workspace_summary_service.get_settings",
        return_value=SimpleNamespace(APP_VERSION="test-version"),
    )
    mocker.patch(
        "app.services.workspace_summary_service.generate_canonical_hash",
        return_value=("fingerprint", "hash"),
    )
    mocker.patch("app.services.workspace_summary_service.execution_registry.mark_running")
    mocker.patch("app.services.workspace_summary_service.execution_registry.start_stage")
    mocker.patch("app.services.workspace_summary_service.execution_registry.complete_stage")
    mocker.patch(
        "app.services.workspace_summary_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: lineage_capture.update(kwargs),
    )
    mocker.patch(
        "app.services.workspace_summary_service.retrieve_stateful_portfolio_input",
        side_effect=lambda **kwargs: (
            captured.update({"start_date": kwargs["start_date"]})
            or SimpleNamespace(retrieval_metadata=SimpleNamespace(chunk_count=3, page_count=7))
        ),
    )
    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_portfolio_valuation_input",
        return_value=SimpleNamespace(
            performance_start_date=pd.Timestamp("2026-01-01").date(),
            observations=[{"perf_date": "2026-05-30"}],
            valuation_points=[
                {
                    "perf_date": "2026-05-30",
                    "begin_mv": 100.0,
                    "bod_cf": 0.0,
                    "eod_cf": 0.0,
                    "mgmt_fees": 0.0,
                    "end_mv": 101.0,
                },
                {
                    "perf_date": "2026-06-30",
                    "begin_mv": 101.0,
                    "bod_cf": 0.0,
                    "eod_cf": 0.0,
                    "mgmt_fees": 0.0,
                    "end_mv": 102.0,
                },
            ],
        ),
    )
    mocker.patch(
        "app.services.workspace_summary_service._calculate_workspace_twr_artifacts",
        return_value=WorkspaceTWRArtifacts(
            daily_results_df=pd.DataFrame(
                {
                    "perf_date": [pd.Timestamp("2026-05-30T10:00:00Z"), "2026-06-30"],
                    "daily_ror": [1.0, 0.990099],
                    "perf_reset": [False, False],
                    "final_cum_ror": [1.0, 2.0],
                }
            ),
            diagnostics=Diagnostics(
                nip_days=0,
                reset_days=0,
                effective_period_start=pd.Timestamp("2026-05-30").date(),
                notes=[],
            ),
        ),
    )

    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-06-30",
            "performance_start_date": "2026-01-01",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [
                {"period": "1D", "frequencies": ["daily"]},
                {"period": "1M", "frequencies": ["monthly"]},
            ],
        }
    )

    response = await calculate_workspace_summary_async(request)

    assert str(captured["start_date"]) == "2026-05-31"
    assert response.audit.counts["portfolio_chunk_count"] == 3
    assert lineage_capture["calculation_type"] == ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY
    assert set(response.results_by_period) == {"1D", "1M"}
    one_day = response.results_by_period["1D"]
    assert (
        one_day.portfolio_twr.net.summary.period_return.base == one_day.portfolio_twr.net.summary.cumulative_return.base
    )
    assert one_day.money_weighted_return.period_return == one_day.money_weighted_return.cumulative_return


def test_workspace_summary_stateful_linked_benchmark_resolves_assignment_once(mocker):
    captured: dict[str, object] = {}
    mocker.patch(
        "app.services.workspace_summary_service.get_settings",
        return_value=SimpleNamespace(APP_VERSION="test-version"),
    )
    mocker.patch(
        "app.services.workspace_summary_service.generate_canonical_hash",
        return_value=("fingerprint", "hash"),
    )
    mocker.patch("app.services.workspace_summary_service.execution_registry.mark_running")
    mocker.patch("app.services.workspace_summary_service.execution_registry.start_stage")
    mocker.patch("app.services.workspace_summary_service.execution_registry.complete_stage")
    mocker.patch("app.services.workspace_summary_service.complete_execution_with_lineage")

    async def _resolve_portfolio_input(**_kwargs):
        return SimpleNamespace(
            input_mode="stateful",
            performance_start_date=pd.Timestamp("2025-01-01").date(),
            valuation_points=[
                DailyInputData.model_validate(
                    {
                        "perf_date": "2026-01-02",
                        "begin_mv": 100.0,
                        "bod_cf": 0.0,
                        "eod_cf": 0.0,
                        "mgmt_fees": 0.0,
                        "end_mv": 101.0,
                    }
                )
            ],
            observations=[{"perf_date": "2026-01-02"}],
            source_details={"portfolio_chunk_count": 2, "portfolio_page_count": 4},
        )

    mocker.patch(
        "app.services.workspace_summary_service._resolve_workspace_portfolio_input_async",
        side_effect=_resolve_portfolio_input,
    )

    async def _get_benchmark_assignment(**kwargs):
        captured["assignment_called"] = True
        return (200, {"benchmark_id": "LINKED-BMK"})

    stateful_input_service = SimpleNamespace(
        get_benchmark_assignment=_get_benchmark_assignment,
    )
    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_input_service",
        return_value=stateful_input_service,
    )

    async def _build_benchmark_input(**kwargs):
        captured["benchmark_id"] = kwargs["benchmark_id"]
        return SimpleNamespace(
            benchmark_currency="USD",
            component_observations=[
                SimpleNamespace(
                    model_dump=lambda mode="python": {
                        "component_id": "IDX1",
                        "perf_date": "2026-01-02",
                        "weight_bop": 1.0,
                        "component_return": 0.01,
                    }
                )
            ],
            benchmark_return_points=[],
            source_details={"chunk_count": 5},
        )

    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_benchmark_input", side_effect=_build_benchmark_input
    )
    mocker.patch(
        "app.services.workspace_summary_service._calculate_workspace_twr_artifacts",
        return_value=WorkspaceTWRArtifacts(
            daily_results_df=pd.DataFrame(
                {
                    "perf_date": [pd.Timestamp("2026-01-02T10:00:00Z")],
                    "daily_ror": [1.0],
                    "perf_reset": [False],
                    "final_cum_ror": [1.0],
                }
            ),
            diagnostics=Diagnostics(
                nip_days=0,
                reset_days=0,
                effective_period_start=pd.Timestamp("2026-01-02").date(),
                notes=[],
            ),
        ),
    )

    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "performance_start_date": "2025-01-01",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
            "include_benchmark": True,
            "benchmark": {"input_mode": "stateful", "stateful_input": {}},
        }
    )

    response = calculate_workspace_summary(request)

    assert captured["assignment_called"] is True
    assert captured["benchmark_id"] == "LINKED-BMK"
    assert response.results_by_period["1D"].benchmark.benchmark_id == "LINKED-BMK"
    assert (
        response.results_by_period["1D"].benchmark.summary.period_return.base
        == response.results_by_period["1D"].benchmark.summary.cumulative_return.base
    )
    assert response.audit.counts["benchmark_chunk_count"] == 5


def test_resolve_stateful_portfolio_start_date_surfaces_upstream_service_errors(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
        }
    )

    async def _get_portfolio_reference(**_kwargs):
        return (503, {})

    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_input_service",
        return_value=SimpleNamespace(get_portfolio_reference=_get_portfolio_reference),
    )

    with pytest.raises(APIError, match="stateful portfolio reference source unavailable"):
        _resolve_stateful_portfolio_start_date(request=request, settings=SimpleNamespace())


def test_resolve_stateful_portfolio_start_date_rejects_invalid_reference_payload(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
        }
    )

    async def _get_portfolio_reference(**_kwargs):
        return (200, {"portfolio_open_date": "not-a-date"})

    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_input_service",
        return_value=SimpleNamespace(get_portfolio_reference=_get_portfolio_reference),
    )

    with pytest.raises(APIError, match="Invalid portfolio_open_date"):
        _resolve_stateful_portfolio_start_date(request=request, settings=SimpleNamespace())


def test_workspace_summary_decimal_or_zero_handles_nullable_pandas_values():
    assert _decimal_or_zero(pd.NA) == Decimal("0")
    assert _decimal_or_zero(float("nan")) == Decimal("0")
    assert _decimal_or_zero(Decimal("12.34")) == Decimal("12.34")


def test_resolve_workspace_benchmark_input_rejects_missing_assignment(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
            "include_benchmark": True,
            "benchmark": {"input_mode": "stateful", "stateful_input": {}},
        }
    )

    async def _get_benchmark_assignment(**_kwargs):
        return (404, {})

    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_input_service",
        return_value=SimpleNamespace(get_benchmark_assignment=_get_benchmark_assignment),
    )

    with pytest.raises(APIError, match="No benchmark assignment found"):
        _resolve_workspace_benchmark_input(
            request=request,
            settings=SimpleNamespace(),
            master_start_date=date(2026, 1, 2),
        )


def test_resolve_workspace_benchmark_input_rejects_assignment_payload_without_benchmark_id(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
            "include_benchmark": True,
            "benchmark": {"input_mode": "stateful", "stateful_input": {}},
        }
    )

    async def _get_benchmark_assignment(**_kwargs):
        return (200, {"benchmark_id": ""})

    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_input_service",
        return_value=SimpleNamespace(get_benchmark_assignment=_get_benchmark_assignment),
    )

    with pytest.raises(APIError, match="benchmark assignment payload missing benchmark_id"):
        _resolve_workspace_benchmark_input(
            request=request,
            settings=SimpleNamespace(),
            master_start_date=date(2026, 1, 2),
        )


def test_build_stateful_workspace_benchmark_input_projects_request_and_source_details(mocker):
    captured_identity: dict[str, object] = {}
    captured_input: dict[str, object] = {}

    async def _resolve_benchmark_identity(**kwargs):
        captured_identity.update(kwargs)
        return SimpleNamespace(benchmark_id="LINKED-BMK", source_details={"resolved_benchmark_assignment": 1})

    async def _build_stateful_benchmark_input(**kwargs):
        captured_input.update(kwargs)
        return SimpleNamespace(
            benchmark_currency="USD",
            component_observations=[],
            benchmark_return_points=[
                SimpleNamespace(model_dump=lambda mode="python": {"perf_date": "2026-01-02", "benchmark_return": 0.01})
            ],
            source_details={"benchmark_chunk_count": 4},
        )

    stateful_input_service = SimpleNamespace()
    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_input_service",
        return_value=stateful_input_service,
    )
    mocker.patch(
        "app.services.workspace_summary_service.resolve_benchmark_identity",
        side_effect=_resolve_benchmark_identity,
    )
    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_benchmark_input",
        side_effect=_build_stateful_benchmark_input,
    )
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "report_ccy": "USD",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
            "include_benchmark": True,
            "benchmark": {"input_mode": "stateful", "stateful_input": {}, "return_source": "vendor_series"},
        }
    )
    assert request.benchmark is not None

    result = _build_stateful_workspace_benchmark_input(
        request=request,
        benchmark=request.benchmark,
        settings=SimpleNamespace(),
        master_start_date=date(2026, 1, 1),
    )

    assert captured_identity["stateful_input_service"] is stateful_input_service
    assert captured_identity["portfolio_id"] == "PORT-1"
    assert captured_identity["reporting_currency"] == "USD"
    assert captured_input["benchmark_id"] == "LINKED-BMK"
    assert captured_input["start_date"] == date(2026, 1, 1)
    assert captured_input["end_date"] == date(2026, 1, 2)
    assert result.input_mode == BenchmarkInputMode.STATEFUL
    assert result.benchmark_id == "LINKED-BMK"
    assert result.source_details == {"resolved_benchmark_assignment": 1, "benchmark_chunk_count": 4}
    assert result.benchmark_request.benchmark_id == "LINKED-BMK"
    assert result.benchmark_request.benchmark_start_date == date(2026, 1, 1)
    assert result.benchmark_request.report_start_date == date(2026, 1, 1)
    assert result.benchmark_request.report_end_date == date(2026, 1, 2)
    assert result.benchmark_request.return_source == "vendor_series"
    assert [point.benchmark_return for point in result.benchmark_request.benchmark_return_points] == [0.01]
    assert result.benchmark_request.component_observations == []


def test_resolve_workspace_benchmark_input_rejects_stateless_payload_missing_required_fields():
    request = WorkspaceSummaryRequest.model_construct(
        calculation_id=uuid4(),
        portfolio_id="PORT-1",
        report_end_date=date(2026, 1, 2),
        report_start_date=None,
        performance_start_date=date(2025, 1, 1),
        periods=[],
        input_mode="stateful",
        stateless_input=None,
        stateful_input={},
        valuation_points=[],
        include_benchmark=True,
        benchmark=SimpleNamespace(input_mode="stateless", stateless_input=None, benchmark_id=None),
        segmentation=None,
        contribution=None,
        attribution=None,
        mwr_method="XIRR",
        solver=SimpleNamespace(),
        currency="USD",
        precision_mode="FLOAT64",
        rounding_precision=6,
        calendar=SimpleNamespace(),
        annualization=SimpleNamespace(),
        output=SimpleNamespace(),
        report_ccy=None,
        currency_mode=None,
        fx=None,
    )

    with pytest.raises(APIError, match="Stateless workspace benchmark requests require benchmark_id"):
        _resolve_workspace_benchmark_input(
            request=request,
            settings=SimpleNamespace(),
            master_start_date=date(2026, 1, 2),
        )


def test_build_stateless_workspace_benchmark_input_projects_vendor_return_points():
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
            "include_benchmark": True,
            "benchmark": {
                "benchmark_id": "BMK-1",
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "benchmark_return_points": [
                        {"perf_date": "2026-01-01", "benchmark_return": 0.01},
                        {"perf_date": "2026-01-02", "benchmark_return": 0.02},
                    ],
                },
            },
        }
    )

    assert request.benchmark is not None
    result = _build_stateless_workspace_benchmark_input(
        request=request,
        benchmark=request.benchmark,
        master_start_date=date(2026, 1, 1),
    )

    assert result.input_mode == BenchmarkInputMode.STATELESS
    assert result.benchmark_id == "BMK-1"
    assert result.source_details == {}
    assert result.benchmark_request.benchmark_id == "BMK-1"
    assert result.benchmark_request.return_source == "vendor_series"
    assert result.benchmark_request.benchmark_start_date == date(2026, 1, 1)
    assert result.benchmark_request.report_start_date == date(2026, 1, 1)
    assert result.benchmark_request.component_observations == []
    assert [point.benchmark_return for point in result.benchmark_request.benchmark_return_points] == [0.01, 0.02]


def test_resolve_workspace_portfolio_input_rejects_stateless_request_without_performance_start_date():
    request = WorkspaceSummaryRequest.model_construct(
        calculation_id=uuid4(),
        portfolio_id="PORT-1",
        report_end_date=date(2026, 1, 2),
        report_start_date=None,
        performance_start_date=None,
        periods=[],
        input_mode="stateless",
        stateless_input=SimpleNamespace(
            valuation_points=[
                DailyInputData.model_validate({"perf_date": "2026-01-02", "begin_mv": 100.0, "end_mv": 101.0})
            ]
        ),
        stateful_input=None,
        valuation_points=[],
        include_benchmark=False,
        benchmark=None,
        segmentation=None,
        contribution=None,
        attribution=None,
        mwr_method="XIRR",
        solver=SimpleNamespace(),
        currency="USD",
        precision_mode="FLOAT64",
        rounding_precision=6,
        calendar=SimpleNamespace(),
        annualization=SimpleNamespace(),
        output=SimpleNamespace(),
        report_ccy=None,
        currency_mode=None,
        fx=None,
    )

    with pytest.raises(APIError, match="performance_start_date is required for stateless workspace summary"):
        _resolve_workspace_portfolio_input(request=request, settings=SimpleNamespace())


def test_build_stateless_workspace_portfolio_input_projects_values_and_source_details():
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "performance_start_date": "2026-01-01",
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [
                    {"perf_date": "2026-01-01", "begin_mv": 100.0, "end_mv": 101.0},
                    {"perf_date": "2026-01-02", "begin_mv": 101.0, "end_mv": 102.0},
                ]
            },
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
        }
    )

    result = _build_stateless_workspace_portfolio_input(request)

    assert result.input_mode == "stateless"
    assert result.performance_start_date == date(2026, 1, 1)
    assert [point.perf_date for point in result.valuation_points] == [date(2026, 1, 1), date(2026, 1, 2)]
    assert [observation["perf_date"] for observation in result.observations] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
    ]
    assert result.source_details == {"portfolio_chunk_count": 0, "portfolio_page_count": 0}


def test_build_stateful_workspace_portfolio_input_projects_retrieval_and_source_details(mocker):
    captured: dict[str, object] = {}
    source_input = SimpleNamespace(retrieval_metadata=SimpleNamespace(chunk_count=3, page_count=7))

    async def _retrieve_stateful_portfolio_input(**kwargs):
        captured.update(kwargs)
        return source_input

    mocker.patch(
        "app.services.workspace_summary_service.retrieve_stateful_portfolio_input",
        side_effect=_retrieve_stateful_portfolio_input,
    )
    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_portfolio_valuation_input",
        return_value=SimpleNamespace(
            performance_start_date=date(2026, 1, 1),
            observations=[{"perf_date": "2026-01-02"}],
            valuation_points=[
                {
                    "perf_date": "2026-01-02",
                    "begin_mv": 100.0,
                    "bod_cf": 0.0,
                    "eod_cf": 0.0,
                    "mgmt_fees": 0.0,
                    "end_mv": 101.0,
                }
            ],
        ),
    )
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "report_start_date": "2026-01-01",
            "performance_start_date": "2026-01-01",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        }
    )

    result = _build_stateful_workspace_portfolio_input(request=request, settings=SimpleNamespace())

    assert captured["portfolio_id"] == "PORT-1"
    assert captured["as_of_date"] == date(2026, 1, 2)
    assert captured["start_date"] == date(2026, 1, 1)
    assert captured["end_date"] == date(2026, 1, 2)
    assert captured["consumer_system"] == "lotus-performance"
    assert result.input_mode == "stateful"
    assert result.performance_start_date == date(2026, 1, 1)
    assert [point.perf_date for point in result.valuation_points] == [date(2026, 1, 2)]
    assert result.observations == [{"perf_date": "2026-01-02"}]
    assert result.source_details == {"portfolio_chunk_count": 3, "portfolio_page_count": 7}


def test_workspace_observation_in_master_window_accepts_bounded_string_dates():
    assert _workspace_observation_in_master_window(
        {"perf_date": "2026-01-02"},
        master_start_date=date(2026, 1, 1),
        report_end_date=date(2026, 1, 2),
    )


def test_workspace_observation_in_master_window_rejects_dates_outside_window():
    assert not _workspace_observation_in_master_window(
        {"perf_date": "2025-12-31"},
        master_start_date=date(2026, 1, 1),
        report_end_date=date(2026, 1, 2),
    )


def test_workspace_observation_in_master_window_rejects_non_string_dates():
    assert not _workspace_observation_in_master_window(
        {"perf_date": date(2026, 1, 2)},
        master_start_date=date(2026, 1, 1),
        report_end_date=date(2026, 1, 2),
    )


def test_workspace_summary_audit_counts_projects_portfolio_counts_without_benchmark():
    portfolio_input = ResolvedWorkspacePortfolioInput(
        input_mode="stateful",
        performance_start_date=date(2026, 1, 1),
        valuation_points=[
            DailyInputData.model_validate({"perf_date": "2026-01-01", "begin_mv": 100.0, "end_mv": 101.0}),
            DailyInputData.model_validate({"perf_date": "2026-01-02", "begin_mv": 101.0, "end_mv": 102.0}),
        ],
        observations=[],
        source_details={"portfolio_chunk_count": 3, "portfolio_page_count": 7},
    )

    assert _workspace_summary_audit_counts(
        portfolio_input=portfolio_input,
        benchmark_input=None,
        results_by_period={"1D": SimpleNamespace()},
    ) == {
        "input_rows": 2,
        "periods_resolved": 1,
        "portfolio_chunk_count": 3,
        "portfolio_page_count": 7,
        "benchmark_chunk_count": 0,
    }


def test_workspace_summary_audit_counts_projects_benchmark_chunk_count():
    portfolio_input = ResolvedWorkspacePortfolioInput(
        input_mode="stateful",
        performance_start_date=date(2026, 1, 1),
        valuation_points=[],
        observations=[],
        source_details={},
    )
    benchmark_input = SimpleNamespace(source_details={"chunk_count": 5})

    assert _workspace_summary_audit_counts(
        portfolio_input=portfolio_input,
        benchmark_input=benchmark_input,
        results_by_period={"1D": SimpleNamespace(), "1M": SimpleNamespace()},
    ) == {
        "input_rows": 0,
        "periods_resolved": 2,
        "portfolio_chunk_count": 0,
        "portfolio_page_count": 0,
        "benchmark_chunk_count": 5,
    }


def test_workspace_summary_meta_projects_request_identity_and_master_window():
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-06-30",
            "report_ccy": "USD",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [
                {"period": "1M", "frequencies": ["daily"]},
                {"period": "YTD", "frequencies": ["monthly"]},
            ],
        }
    )

    meta = _workspace_summary_meta(
        request=request,
        settings=SimpleNamespace(APP_VERSION="test-version"),
        resolved_periods=[
            ResolvedWorkspacePeriod(name="1M", start_date=date(2026, 6, 1), end_date=date(2026, 6, 30)),
            ResolvedWorkspacePeriod(name="YTD", start_date=date(2026, 1, 1), end_date=date(2026, 6, 30)),
        ],
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
    )

    assert meta.calculation_id == request.calculation_id
    assert meta.engine_version == "test-version"
    assert meta.precision_mode == request.precision_mode
    assert meta.annualization == request.annualization
    assert meta.calendar == request.calendar
    assert meta.periods == {
        "requested": ["1M", "YTD"],
        "master_start": "2026-01-01",
        "master_end": "2026-06-30",
    }
    assert meta.input_fingerprint == "input-fingerprint"
    assert meta.calculation_hash == "calculation-hash"
    assert meta.report_ccy == "USD"


def test_build_workspace_summary_response_projects_summary_inputs_and_audit_counts(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "performance_start_date": "2026-01-01",
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [
                    {"perf_date": "2026-01-01", "begin_mv": 100.0, "end_mv": 101.0},
                    {"perf_date": "2026-01-02", "begin_mv": 101.0, "end_mv": 103.0},
                ]
            },
            "periods": [{"period": "1D", "frequencies": ["daily", "monthly"]}],
        }
    )
    portfolio_input = ResolvedWorkspacePortfolioInput(
        input_mode="stateless",
        performance_start_date=date(2026, 1, 1),
        valuation_points=[
            DailyInputData.model_validate({"perf_date": "2026-01-01", "begin_mv": 100.0, "end_mv": 101.0}),
            DailyInputData.model_validate({"perf_date": "2026-01-02", "begin_mv": 101.0, "end_mv": 103.0}),
        ],
        observations=[],
        source_details={"portfolio_chunk_count": 2, "portfolio_page_count": 1},
    )
    return_value = WorkspaceReturnValue(base=1.0)
    economics = WorkspaceEconomicContext(
        begin_market_value=100.0,
        end_market_value=103.0,
        beginning_cash_flow=0.0,
        ending_cash_flow=0.0,
        fees=0.0,
        net_cash_flow=0.0,
        flow_adjusted_end_market_value=103.0,
    )
    performance_block = WorkspacePerformanceBlock(
        summary=WorkspaceEconomicReturnSummary(
            economics=economics,
            period_return=return_value,
            cumulative_return=return_value,
            annualized_return=return_value,
        ),
        breakdowns={},
    )
    period_result = WorkspacePeriodSummaryResult(
        portfolio_twr=WorkspaceBasisPair(net=performance_block, gross=performance_block),
        benchmark=None,
        active=None,
        money_weighted_return=WorkspaceMoneyWeightedReturnSummary(
            input_mode="stateless",
            method="XIRR",
            period_return=1.0,
            cumulative_return=1.0,
            annualized_return=1.0,
            economics=economics,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            notes=[],
        ),
    )
    period_builder = mocker.patch(
        "app.services.workspace_summary_service._build_workspace_results_by_period",
        return_value={"1D": period_result},
    )
    resolved_period = ResolvedWorkspacePeriod(name="1D", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))

    response = _build_workspace_summary_response(
        request=request,
        settings=SimpleNamespace(APP_VERSION="test-version"),
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
        resolved_periods=[resolved_period],
        portfolio_input=portfolio_input,
        benchmark_input=None,
        net_artifacts=WorkspaceTWRArtifacts(
            daily_results_df=pd.DataFrame({"perf_date": ["2026-01-01", "2026-01-02"]}),
            diagnostics=Diagnostics(
                nip_days=0,
                reset_days=0,
                effective_period_start=date(2026, 1, 1),
                notes=["net-note"],
            ),
        ),
        gross_artifacts=WorkspaceTWRArtifacts(
            daily_results_df=pd.DataFrame({"perf_date": ["2026-01-01", "2026-01-02"]}),
            diagnostics=Diagnostics(
                nip_days=0,
                reset_days=0,
                effective_period_start=date(2026, 1, 1),
                notes=["gross-note"],
            ),
        ),
    )

    assert response.calculation_id == request.calculation_id
    assert response.portfolio_id == "PORT-1"
    assert response.input_mode == request.input_mode
    assert response.results_by_period == {"1D": period_result}
    assert response.meta.input_fingerprint == "input-fingerprint"
    assert response.meta.calculation_hash == "calculation-hash"
    assert response.diagnostics.notes == ["net-note"]
    assert response.audit.counts == {
        "input_rows": 2,
        "periods_resolved": 1,
        "portfolio_chunk_count": 2,
        "portfolio_page_count": 1,
        "benchmark_chunk_count": 0,
    }
    period_kwargs = period_builder.call_args.kwargs
    assert period_kwargs["request"] is request
    assert period_kwargs["resolved_periods"] == [resolved_period]
    assert period_kwargs["portfolio_input"] is portfolio_input
    assert period_kwargs["benchmark_input"] is None
    assert period_kwargs["benchmark_daily_df"] is None
    assert period_kwargs["requested_frequencies"] == {"1D": [Frequency.DAILY, Frequency.MONTHLY]}
    assert period_kwargs["valuation_df"]["perf_date"].tolist() == [date(2026, 1, 1), date(2026, 1, 2)]
    assert period_kwargs["net_daily_results_df"]["perf_date"].tolist() == [date(2026, 1, 1), date(2026, 1, 2)]
    assert period_kwargs["gross_daily_results_df"]["perf_date"].tolist() == [date(2026, 1, 1), date(2026, 1, 2)]


def test_build_workspace_results_by_period_skips_empty_periods_and_projects_summaries(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-03",
            "performance_start_date": "2026-01-01",
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [
                    {"perf_date": "2026-01-01", "begin_mv": 100.0, "end_mv": 101.0},
                    {"perf_date": "2026-01-02", "begin_mv": 101.0, "end_mv": 102.0},
                ]
            },
            "periods": [
                {"period": "1D", "frequencies": ["daily"]},
                {"period": "YTD", "frequencies": ["monthly"]},
            ],
        }
    )
    return_value = WorkspaceReturnValue(base=1.0)
    performance_block = WorkspacePerformanceBlock(
        summary=WorkspaceEconomicReturnSummary(
            economics=WorkspaceEconomicContext(
                begin_market_value=100.0,
                end_market_value=102.0,
                beginning_cash_flow=0.0,
                ending_cash_flow=0.0,
                fees=0.0,
                net_cash_flow=0.0,
                flow_adjusted_end_market_value=102.0,
            ),
            period_return=return_value,
            cumulative_return=return_value,
            annualized_return=return_value,
        ),
        breakdowns={},
    )
    mwr_summary = WorkspaceMoneyWeightedReturnSummary(
        input_mode="stateless",
        method="XIRR",
        period_return=1.0,
        cumulative_return=1.0,
        annualized_return=1.0,
        economics=performance_block.summary.economics,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        notes=[],
    )
    performance_builder = mocker.patch(
        "app.services.workspace_summary_service._build_workspace_performance_block",
        return_value=performance_block,
    )
    mocker.patch(
        "app.services.workspace_summary_service._build_workspace_mwr_summary",
        return_value=mwr_summary,
    )

    results = _build_workspace_results_by_period(
        request=request,
        resolved_periods=[
            ResolvedWorkspacePeriod(name="1D", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)),
            ResolvedWorkspacePeriod(name="YTD", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2)),
        ],
        portfolio_input=SimpleNamespace(input_mode="stateless"),
        valuation_df=pd.DataFrame(
            [
                {"perf_date": date(2026, 1, 1), "begin_mv": 100.0, "end_mv": 101.0},
                {"perf_date": date(2026, 1, 2), "begin_mv": 101.0, "end_mv": 102.0},
            ]
        ),
        net_daily_results_df=pd.DataFrame({"perf_date": [date(2026, 1, 1), date(2026, 1, 2)]}),
        gross_daily_results_df=pd.DataFrame({"perf_date": [date(2026, 1, 1), date(2026, 1, 2)]}),
        benchmark_input=None,
        benchmark_daily_df=None,
        requested_frequencies={"1D": []},
    )

    assert list(results) == ["1D"]
    assert results["1D"].portfolio_twr.net.summary.period_return.base == 1.0
    assert results["1D"].portfolio_twr.gross.summary.cumulative_return.base == 1.0
    assert results["1D"].benchmark is None
    assert results["1D"].active is None
    assert results["1D"].money_weighted_return is mwr_summary
    assert performance_builder.call_count == 2


def test_build_workspace_period_summary_result_projects_period_blocks(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-03",
            "performance_start_date": "2026-01-01",
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [
                    {"perf_date": "2026-01-01", "begin_mv": 100.0, "end_mv": 101.0},
                    {"perf_date": "2026-01-02", "begin_mv": 101.0, "end_mv": 102.0},
                ]
            },
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
        }
    )
    return_value = WorkspaceReturnValue(base=1.0)
    performance_block = WorkspacePerformanceBlock(
        summary=WorkspaceEconomicReturnSummary(
            economics=WorkspaceEconomicContext(
                begin_market_value=100.0,
                end_market_value=102.0,
                beginning_cash_flow=0.0,
                ending_cash_flow=0.0,
                fees=0.0,
                net_cash_flow=0.0,
                flow_adjusted_end_market_value=102.0,
            ),
            period_return=return_value,
            cumulative_return=return_value,
            annualized_return=return_value,
        ),
        breakdowns={},
    )
    mwr_summary = WorkspaceMoneyWeightedReturnSummary(
        input_mode="stateless",
        method="XIRR",
        period_return=1.0,
        cumulative_return=1.0,
        annualized_return=1.0,
        economics=performance_block.summary.economics,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        notes=[],
    )
    performance_builder = mocker.patch(
        "app.services.workspace_summary_service._build_workspace_performance_block",
        return_value=performance_block,
    )
    benchmark_builder = mocker.patch(
        "app.services.workspace_summary_service._build_workspace_benchmark_and_active_blocks",
        return_value=(None, None),
    )
    mwr_builder = mocker.patch(
        "app.services.workspace_summary_service._build_workspace_mwr_summary",
        return_value=mwr_summary,
    )
    resolved_period = ResolvedWorkspacePeriod(name="1D", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))

    result = _build_workspace_period_summary_result(
        request=request,
        resolved_period=resolved_period,
        portfolio_input=SimpleNamespace(input_mode="stateless"),
        portfolio_slice=pd.DataFrame(
            [
                {"perf_date": date(2026, 1, 1), "begin_mv": 100.0, "end_mv": 101.0},
                {"perf_date": date(2026, 1, 2), "begin_mv": 101.0, "end_mv": 102.0},
            ]
        ),
        net_daily_results_df=pd.DataFrame({"perf_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]}),
        gross_daily_results_df=pd.DataFrame({"perf_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]}),
        benchmark_input=None,
        benchmark_daily_df=None,
        frequencies=[],
    )

    assert result.portfolio_twr.net is performance_block
    assert result.portfolio_twr.gross is performance_block
    assert result.benchmark is None
    assert result.active is None
    assert result.money_weighted_return is mwr_summary
    assert performance_builder.call_count == 2
    assert [call.kwargs["period_daily_slice"]["perf_date"].tolist() for call in performance_builder.call_args_list] == [
        [date(2026, 1, 1), date(2026, 1, 2)],
        [date(2026, 1, 1), date(2026, 1, 2)],
    ]
    benchmark_builder.assert_called_once()
    mwr_builder.assert_called_once()
    mwr_kwargs = mwr_builder.call_args.kwargs
    assert mwr_kwargs["period"] is resolved_period
    assert mwr_kwargs["input_mode"] == "stateless"
    assert mwr_kwargs["request"] is request
    assert mwr_kwargs["period_slice"]["perf_date"].tolist() == [date(2026, 1, 1), date(2026, 1, 2)]


def test_build_workspace_period_twr_pair_slices_net_and_gross_daily_results(mocker):
    return_value = WorkspaceReturnValue(base=1.0)
    net_block = WorkspacePerformanceBlock(
        summary=WorkspaceEconomicReturnSummary(
            economics=WorkspaceEconomicContext(
                begin_market_value=100.0,
                end_market_value=102.0,
                beginning_cash_flow=0.0,
                ending_cash_flow=0.0,
                fees=0.0,
                net_cash_flow=0.0,
                flow_adjusted_end_market_value=102.0,
            ),
            period_return=return_value,
            cumulative_return=return_value,
            annualized_return=return_value,
        ),
        breakdowns={},
    )
    gross_block = net_block.model_copy(deep=True)
    performance_builder = mocker.patch(
        "app.services.workspace_summary_service._build_workspace_performance_block",
        side_effect=[net_block, gross_block],
    )
    portfolio_slice = pd.DataFrame(
        [
            {"perf_date": date(2026, 1, 1), "begin_mv": 100.0, "end_mv": 101.0},
            {"perf_date": date(2026, 1, 2), "begin_mv": 101.0, "end_mv": 102.0},
        ]
    )
    net_daily_results_df = pd.DataFrame({"perf_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]})
    gross_daily_results_df = pd.DataFrame({"perf_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]})

    result = _build_workspace_period_twr_pair(
        resolved_period=ResolvedWorkspacePeriod(name="1D", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)),
        portfolio_slice=portfolio_slice,
        net_daily_results_df=net_daily_results_df,
        gross_daily_results_df=gross_daily_results_df,
        frequencies=[],
        annualization=SimpleNamespace(),
    )

    assert result.net is net_block
    assert result.gross is gross_block
    assert performance_builder.call_count == 2
    assert [call.kwargs["period_daily_slice"]["perf_date"].tolist() for call in performance_builder.call_args_list] == [
        [date(2026, 1, 1), date(2026, 1, 2)],
        [date(2026, 1, 1), date(2026, 1, 2)],
    ]
    assert performance_builder.call_args_list[0].kwargs["full_daily_df"] is net_daily_results_df
    assert performance_builder.call_args_list[1].kwargs["full_daily_df"] is gross_daily_results_df


def test_build_workspace_performance_breakdowns_uses_period_and_cumulative_windows(mocker):
    valuation_df = pd.DataFrame(
        [
            {
                "perf_date": date(2026, 1, 1),
                "begin_mv": Decimal("100"),
                "end_mv": Decimal("101"),
                "bod_cf": Decimal("0"),
                "eod_cf": Decimal("0"),
                "mgmt_fees": Decimal("0"),
            },
            {
                "perf_date": date(2026, 1, 2),
                "begin_mv": Decimal("101"),
                "end_mv": Decimal("103"),
                "bod_cf": Decimal("0"),
                "eod_cf": Decimal("1"),
                "mgmt_fees": Decimal("0.25"),
            },
            {
                "perf_date": date(2026, 1, 3),
                "begin_mv": Decimal("103"),
                "end_mv": Decimal("104"),
                "bod_cf": Decimal("0"),
                "eod_cf": Decimal("0"),
                "mgmt_fees": Decimal("0"),
            },
        ]
    )
    period_daily_slice = pd.DataFrame({"perf_date": [date(2026, 1, 1), date(2026, 1, 2)]})
    full_daily_df = pd.DataFrame({"perf_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]})
    return_calculator = mocker.patch(
        "app.services.workspace_summary_service._calculate_total_return_from_slice",
        side_effect=["period-decomposition", "cumulative-decomposition"],
    )
    mocker.patch(
        "app.services.workspace_summary_service._build_return_value_from_decomposition",
        side_effect=[
            SimpleNamespace(base=Decimal("2.0"), local=None, fx=None),
            SimpleNamespace(base=Decimal("3.0"), local=None, fx=None),
        ],
    )
    mocker.patch(
        "app.services.workspace_summary_service._iter_frequency_windows",
        return_value=[("2026-01-02", date(2026, 1, 2), date(2026, 1, 2), valuation_df.iloc[[1]])],
    )

    breakdowns = _build_workspace_performance_breakdowns(
        portfolio_slice=valuation_df,
        period_daily_slice=period_daily_slice,
        full_daily_df=full_daily_df,
        frequencies=[Frequency.DAILY],
        annualization=SimpleNamespace(),
    )

    item = breakdowns[Frequency.DAILY][0]
    assert item.period == "2026-01-02"
    assert item.period_start == date(2026, 1, 2)
    assert item.period_end == date(2026, 1, 2)
    assert item.economics.end_market_value == Decimal("103")
    assert item.period_return.base == Decimal("2.0")
    assert item.cumulative_return.base == Decimal("3.0")
    assert item.annualized_return.base == Decimal("3.0")
    assert return_calculator.call_args_list[0].args[0]["perf_date"].tolist() == [date(2026, 1, 2)]
    assert return_calculator.call_args_list[1].args[0]["perf_date"].tolist() == [
        date(2026, 1, 1),
        date(2026, 1, 2),
    ]
    assert return_calculator.call_args_list[0].args[1] is full_daily_df
    assert return_calculator.call_args_list[1].args[1] is full_daily_df


def test_resolve_stateful_portfolio_start_date_rejects_missing_open_date(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
        }
    )

    async def _get_portfolio_reference(**_kwargs):
        return (200, {})

    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_input_service",
        return_value=SimpleNamespace(get_portfolio_reference=_get_portfolio_reference),
    )

    with pytest.raises(APIError, match="Stateful source missing portfolio_open_date"):
        _resolve_stateful_portfolio_start_date(request=request, settings=SimpleNamespace())


def test_build_mwr_cash_flows_keeps_bod_and_eod_movements():
    period_slice = pd.DataFrame(
        {
            "perf_date": [date(2026, 1, 2), date(2026, 1, 3)],
            "bod_cf": [10.0, 0.0],
            "eod_cf": [0.0, -5.0],
        }
    )

    cash_flows = _build_mwr_cash_flows(period_slice)

    assert [(item.amount, item.date) for item in cash_flows] == [(10.0, date(2026, 1, 2)), (-5.0, date(2026, 1, 3))]


def test_build_mwr_cash_flows_includes_carry_forward_capital_breaks():
    period_slice = pd.DataFrame(
        {
            "perf_date": [date(2026, 1, 2), date(2026, 1, 3)],
            "begin_mv": [1000.0, 1250.0],
            "end_mv": [1010.0, 1260.0],
            "bod_cf": [0.0, 10.0],
            "eod_cf": [0.0, -5.0],
            "mgmt_fees": [0.0, 0.0],
        }
    )

    cash_flows = _build_mwr_cash_flows(period_slice)
    economics = _build_economic_context(period_slice)

    assert [(item.amount, item.date) for item in cash_flows] == [
        (250.0, date(2026, 1, 3)),
        (-5.0, date(2026, 1, 3)),
    ]
    assert economics.beginning_cash_flow == Decimal("10.0")
    assert economics.ending_cash_flow == Decimal("-5.0")
    assert economics.net_cash_flow == Decimal("5.0")
    assert economics.flow_adjusted_end_market_value == Decimal("1255.0")


def test_annualize_percentage_returns_original_value_when_elapsed_measure_is_non_positive():
    annualization = SimpleNamespace(enabled=True, periods_per_year=None, basis="BUS/252")

    assert (
        _annualize_percentage(
            12.5,
            start_date=date(2024, 1, 1),
            end_date=date(2025, 1, 2),
            annualization=annualization,
            business_day_count=0,
        )
        == 12.5
    )


def test_annualize_percentage_returns_original_value_when_annualization_is_disabled():
    annualization = SimpleNamespace(enabled=False, periods_per_year=252, basis="BUS/252")

    annualized = _annualize_percentage(
        Decimal("21.0"),
        start_date=date(2025, 1, 1),
        end_date=date(2026, 12, 31),
        annualization=annualization,
        business_day_count=522,
    )

    assert annualized == Decimal("21.0")


def test_annualize_return_value_preserves_components_when_annualization_is_disabled():
    annualization = SimpleNamespace(enabled=False, periods_per_year=365, basis="ACT/365")
    measured_return = WorkspaceReturnValue(base=Decimal("21.0"), local=Decimal("20.0"), fx=Decimal("1.0"))

    annualized = _annualize_return_value(
        measured_return,
        start_date=date(2025, 1, 1),
        end_date=date(2026, 12, 31),
        annualization=annualization,
        business_day_count=522,
    )

    assert annualized.base == Decimal("21.0")
    assert annualized.local == Decimal("20.0")
    assert annualized.fx == Decimal("1.0")


def test_annualize_percentage_projects_elapsed_positive_multi_year_return():
    annualization = SimpleNamespace(enabled=True, periods_per_year=365, basis="CAL/365")

    annualized = _annualize_percentage(
        Decimal("12.5"),
        start_date=date(2025, 1, 1),
        end_date=date(2026, 2, 4),
        annualization=annualization,
        business_day_count=286,
    )

    assert annualized == Decimal("11.34652730611459486863045300")


def test_annualization_periods_and_elapsed_measure_uses_business_day_basis_defaults():
    assert _annualization_periods_and_elapsed_measure(
        annualization=SimpleNamespace(periods_per_year=None, basis="BUS/252"),
        business_day_count=200,
        elapsed_days=365,
    ) == (252, 200)


def test_annualization_periods_and_elapsed_measure_uses_calendar_basis_and_explicit_periods():
    assert _annualization_periods_and_elapsed_measure(
        annualization=SimpleNamespace(periods_per_year=360, basis="CAL/365"),
        business_day_count=200,
        elapsed_days=400,
    ) == (360, 400)


def test_date_from_boundary_rejects_unsupported_boundary_values():
    with pytest.raises(TypeError, match="Unsupported date boundary value"):
        _date_from_boundary("2026-01-02")


def test_date_from_boundary_accepts_pandas_timestamp():
    assert _date_from_boundary(pd.Timestamp("2026-01-02")) == date(2026, 1, 2)


def test_build_workspace_benchmark_and_active_blocks_projects_relative_returns(mocker):
    benchmark_return = WorkspaceReturnValue(base=2.0)
    benchmark_block = SimpleNamespace(
        summary=WorkspaceReturnSummary(
            period_return=benchmark_return,
            cumulative_return=benchmark_return,
            annualized_return=benchmark_return,
        )
    )
    mocker.patch(
        "app.services.workspace_summary_service._build_workspace_benchmark_block",
        return_value=benchmark_block,
    )
    portfolio_return = WorkspaceReturnValue(base=10.0)
    portfolio_summary = SimpleNamespace(
        summary=WorkspaceReturnSummary(
            period_return=portfolio_return,
            cumulative_return=portfolio_return,
            annualized_return=portfolio_return,
        )
    )

    resolved_benchmark, active = _build_workspace_benchmark_and_active_blocks(
        benchmark_input=SimpleNamespace(),
        benchmark_daily_df=pd.DataFrame({"date": [date(2026, 1, 2)]}),
        resolved_period=ResolvedWorkspacePeriod(
            name="1D",
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 2),
        ),
        frequencies=[],
        annualization=SimpleNamespace(),
        net_summary=portfolio_summary,
        gross_summary=portfolio_summary,
    )

    assert resolved_benchmark is benchmark_block
    assert active.net.period_return.base == 8.0
    assert active.gross.annualized_return.base == 8.0


def test_build_workspace_active_block_projects_net_and_gross_relative_returns():
    benchmark_return = WorkspaceReturnValue(base=2.0)
    benchmark_block = SimpleNamespace(
        summary=WorkspaceReturnSummary(
            period_return=benchmark_return,
            cumulative_return=WorkspaceReturnValue(base=3.0),
            annualized_return=WorkspaceReturnValue(base=4.0),
        )
    )
    net_summary = SimpleNamespace(
        summary=WorkspaceReturnSummary(
            period_return=WorkspaceReturnValue(base=10.0),
            cumulative_return=WorkspaceReturnValue(base=11.0),
            annualized_return=WorkspaceReturnValue(base=12.0),
        )
    )
    gross_summary = SimpleNamespace(
        summary=WorkspaceReturnSummary(
            period_return=WorkspaceReturnValue(base=13.0),
            cumulative_return=WorkspaceReturnValue(base=14.0),
            annualized_return=WorkspaceReturnValue(base=15.0),
        )
    )

    active = _build_workspace_active_block(
        benchmark_block=benchmark_block,
        net_summary=net_summary,
        gross_summary=gross_summary,
    )

    assert active.net.period_return.base == 8.0
    assert active.net.cumulative_return.base == 8.0
    assert active.net.annualized_return.base == 8.0
    assert active.gross.period_return.base == 11.0
    assert active.gross.cumulative_return.base == 11.0
    assert active.gross.annualized_return.base == 11.0


def test_build_workspace_benchmark_daily_df_uses_observation_date_series():
    benchmark_request = BenchmarkPerformanceRequest.model_validate(
        {
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "benchmark_currency": "USD",
            "return_source": "vendor_series",
            "benchmark_return_points": [
                {"perf_date": "2026-03-30", "benchmark_return": 0.01},
                {"perf_date": "2026-03-31", "benchmark_return": 0.02},
            ],
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "report_start_date": "2026-03-30",
        }
    )
    benchmark_input = ResolvedWorkspaceBenchmarkInput(
        benchmark_request=benchmark_request,
        input_mode=BenchmarkInputMode.STATELESS,
        benchmark_id="BMK_VENDOR",
        source_details={},
    )

    daily_df = _build_workspace_benchmark_daily_df(benchmark_input)

    assert daily_df is not None
    assert daily_df["date"].tolist() == [date(2026, 3, 30), date(2026, 3, 31)]


def test_workspace_summary_diagnostics_notes_preserve_base_notes_and_benchmark_context():
    diagnostics = Diagnostics(
        notes=["source note"],
        nip_days=0,
        reset_days=0,
        effective_period_start=date(2026, 3, 30),
    )
    benchmark_request = BenchmarkPerformanceRequest.model_validate(
        {
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2026-03-30",
            "report_end_date": "2026-03-31",
            "benchmark_currency": "USD",
            "return_source": "vendor_series",
            "benchmark_return_points": [{"perf_date": "2026-03-31", "benchmark_return": 0.02}],
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "report_start_date": "2026-03-30",
        }
    )
    benchmark_input = ResolvedWorkspaceBenchmarkInput(
        benchmark_request=benchmark_request,
        input_mode=BenchmarkInputMode.STATELESS,
        benchmark_id="BMK_VENDOR",
        source_details={},
    )

    assert _workspace_summary_diagnostics_notes(diagnostics=diagnostics, benchmark_input=None) == ["source note"]
    assert _workspace_summary_diagnostics_notes(
        diagnostics=diagnostics,
        benchmark_input=benchmark_input,
    ) == [
        "source note",
        "Benchmark summary uses stateless benchmark input with vendor_series returns.",
    ]

    projected = _workspace_summary_diagnostics(
        net_artifacts=WorkspaceTWRArtifacts(daily_results_df=pd.DataFrame(), diagnostics=diagnostics),
        benchmark_input=benchmark_input,
    )

    assert projected.nip_days == 0
    assert projected.reset_days == 0
    assert projected.effective_period_start == date(2026, 3, 30)
    assert projected.notes == [
        "source note",
        "Benchmark summary uses stateless benchmark input with vendor_series returns.",
    ]


def test_resolve_workspace_inputs_rejects_empty_resolved_periods(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "performance_start_date": "2026-01-01",
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [
                    {"perf_date": "2026-01-01", "begin_mv": 100.0, "end_mv": 101.0},
                    {"perf_date": "2026-01-02", "begin_mv": 101.0, "end_mv": 102.0},
                ]
            },
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
        }
    )
    mocker.patch(
        "app.services.workspace_summary_service._resolve_workspace_portfolio_input",
        return_value=ResolvedWorkspacePortfolioInput(
            input_mode="stateless",
            performance_start_date=date(2026, 1, 1),
            valuation_points=[],
            observations=[],
            source_details={},
        ),
    )
    mocker.patch("app.services.workspace_summary_service.resolve_workspace_periods", return_value=[])

    with pytest.raises(APIError, match="No valid workspace periods"):
        _resolve_workspace_inputs(request=request, settings=SimpleNamespace())


def test_build_workspace_benchmark_and_active_blocks_skips_empty_period_slice():
    return_value = WorkspaceReturnValue(base=1.0)
    portfolio_summary = SimpleNamespace(
        summary=WorkspaceReturnSummary(
            period_return=return_value,
            cumulative_return=return_value,
            annualized_return=return_value,
        )
    )

    benchmark_block, active_block = _build_workspace_benchmark_and_active_blocks(
        benchmark_input=SimpleNamespace(),
        benchmark_daily_df=pd.DataFrame({"date": [date(2026, 1, 1)], "benchmark_return": [0.01]}),
        resolved_period=ResolvedWorkspacePeriod(
            name="1D",
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 2),
        ),
        frequencies=[],
        annualization=SimpleNamespace(),
        net_summary=portfolio_summary,
        gross_summary=portfolio_summary,
    )

    assert benchmark_block is None
    assert active_block is None


def test_build_workspace_benchmark_daily_df_preserves_empty_vendor_series():
    benchmark_input = SimpleNamespace(
        benchmark_request=SimpleNamespace(return_source="vendor_series", benchmark_return_points=[])
    )

    daily_df = _build_workspace_benchmark_daily_df(benchmark_input)

    assert daily_df is not None
    assert daily_df.empty


def test_normalize_workspace_daily_results_df_preserves_empty_frame():
    empty_df = pd.DataFrame()

    normalized_df = _normalize_workspace_daily_results_df(empty_df)

    assert normalized_df.empty
    assert list(normalized_df.columns) == []


def test_sum_decimal_column_returns_zero_for_missing_economic_column():
    frame = pd.DataFrame({"begin_mv": [100.0]})

    assert _sum_decimal_column(frame, "mgmt_fees") == Decimal("0")


def test_is_missing_decimal_value_treats_ambiguous_pandas_values_as_present():
    assert _is_missing_decimal_value([None, 1]) is False
