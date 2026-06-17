from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
from fastapi import HTTPException

from app.models.benchmark_analytics_requests import BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import DailyInputData
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.models.workspace_summary_responses import (
    WorkspaceEconomicContext,
    WorkspaceEconomicReturnSummary,
    WorkspaceMoneyWeightedReturnSummary,
    WorkspacePerformanceBlock,
    WorkspaceReturnSummary,
    WorkspaceReturnValue,
)
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY
from app.services.workspace_summary_service import (
    ResolvedWorkspaceBenchmarkInput,
    WorkspaceTWRArtifacts,
    _annualize_percentage,
    _build_economic_context,
    _build_mwr_cash_flows,
    _build_stateful_workspace_portfolio_input,
    _build_stateless_workspace_benchmark_input,
    _build_stateless_workspace_portfolio_input,
    _build_workspace_benchmark_and_active_blocks,
    _build_workspace_benchmark_daily_df,
    _build_workspace_results_by_period,
    _date_from_boundary,
    _decimal_or_zero,
    _longest_workspace_period_days,
    _resolve_stateful_portfolio_start_date,
    _resolve_workspace_benchmark_input,
    _resolve_workspace_portfolio_input,
    _workspace_summary_diagnostics_notes,
    calculate_workspace_summary,
    workspace_longest_requested_window_days,
)
from core.envelope import Diagnostics
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


def test_workspace_summary_stateful_retrieval_uses_longest_requested_window(mocker):
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

    response = calculate_workspace_summary(request)

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
    mocker.patch(
        "app.services.workspace_summary_service._resolve_workspace_portfolio_input",
        return_value=SimpleNamespace(
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
        ),
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

    with pytest.raises(HTTPException, match="stateful portfolio reference source unavailable"):
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

    with pytest.raises(HTTPException, match="Invalid portfolio_open_date"):
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

    with pytest.raises(HTTPException, match="No benchmark assignment found"):
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

    with pytest.raises(HTTPException, match="benchmark assignment payload missing benchmark_id"):
        _resolve_workspace_benchmark_input(
            request=request,
            settings=SimpleNamespace(),
            master_start_date=date(2026, 1, 2),
        )


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

    with pytest.raises(HTTPException, match="Stateless workspace benchmark requests require benchmark_id"):
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

    with pytest.raises(HTTPException, match="performance_start_date is required for stateless workspace summary"):
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

    with pytest.raises(HTTPException, match="Stateful source missing portfolio_open_date"):
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
    annualization = SimpleNamespace(periods_per_year=None, basis="BUS/252")

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
