from datetime import date
from typing import cast

import pandas as pd
import pytest
from fastapi import HTTPException

from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import PerformanceRequest
from app.models.responses import ComparativeAnalyticsBlock, ComparativeSummary, SinglePeriodPerformanceResult
from app.models.twr_requests import TWRInputMode
from app.services.benchmark_calculation_service import BenchmarkCalculationArtifacts
from app.services.twr_service import (
    _as_numeric,
    _build_twr_benchmark_period_blocks,
    _build_twr_lineage_details,
    _build_twr_portfolio_period_block,
    _build_twr_response_model,
    _build_twr_results_by_period,
    _calculate_total_return_from_slice,
    _get_total_cum_ror,
    _rebased_cumulative_ror,
    _resolve_twr_execution_period_scope,
    _resolve_twr_supportability,
    _twr_period_reset_events,
    _TWRBenchmarkPeriodContext,
    _TWRExecutionCalculation,
)
from common.enums import Frequency
from core.periods import ResolvedPeriod
from engine.diagnostics import EngineDiagnostics, EngineResetEvent
from engine.schema import PortfolioColumns


def _twr_request(*, emit_resets: bool = False) -> PerformanceRequest:
    return PerformanceRequest.model_validate(
        {
            "portfolio_id": "P1",
            "performance_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "metric_basis": "NET",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1030.2},
            ],
            "reset_policy": {"emit": emit_resets},
        }
    )


def _daily_twr_results_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.BEGIN_MV.value: 1000.0,
                PortfolioColumns.BOD_CF.value: 0.0,
                PortfolioColumns.EOD_CF.value: 0.0,
                PortfolioColumns.MGMT_FEES.value: 0.0,
                PortfolioColumns.END_MV.value: 1010.0,
                PortfolioColumns.DAILY_ROR.value: 1.0,
                PortfolioColumns.FINAL_CUM_ROR.value: 1.0,
                PortfolioColumns.PERF_RESET.value: 0,
                PortfolioColumns.NIP.value: 0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.BEGIN_MV.value: 1010.0,
                PortfolioColumns.BOD_CF.value: 0.0,
                PortfolioColumns.EOD_CF.value: 0.0,
                PortfolioColumns.MGMT_FEES.value: 0.0,
                PortfolioColumns.END_MV.value: 1030.2,
                PortfolioColumns.DAILY_ROR.value: 2.0,
                PortfolioColumns.FINAL_CUM_ROR.value: 3.02,
                PortfolioColumns.PERF_RESET.value: 0,
                PortfolioColumns.NIP.value: 0,
            },
        ]
    )


def test_resolve_twr_execution_period_scope_projects_periods_frequencies_and_master_window():
    scope = _resolve_twr_execution_period_scope(_twr_request())

    assert [period.name for period in scope.resolved_periods] == ["ITD"]
    assert scope.freqs_by_period == {"ITD": [Frequency.DAILY]}
    assert scope.master_start_date == date(2025, 1, 1)
    assert scope.master_end_date == date(2025, 1, 3)


def test_resolve_twr_execution_period_scope_rejects_unresolved_periods(mocker):
    mocker.patch("app.services.twr_service.resolve_periods", return_value=[])

    with pytest.raises(HTTPException) as exc_info:
        _resolve_twr_execution_period_scope(_twr_request())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "No valid periods could be resolved."


def test_build_twr_results_by_period_builds_portfolio_summary_and_skips_empty_periods():
    request = _twr_request()
    results = _build_twr_results_by_period(
        performance_request=request,
        resolved_periods=[
            ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)),
            ResolvedPeriod(name="YTD", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)),
        ],
        freqs_by_period={"ITD": [Frequency.DAILY], "YTD": [Frequency.DAILY]},
        daily_results_df=_daily_twr_results_df(),
        engine_diagnostics=EngineDiagnostics(),
        benchmark_artifacts=None,
        benchmark_request=None,
        benchmark_input_mode=None,
        resolved_benchmark_id=None,
        benchmark_return_source=BenchmarkReturnSource.CALCULATED,
        master_start_date=date(2025, 1, 1),
    )

    assert list(results) == ["ITD"]
    assert results["ITD"].portfolio.summary.period_return.base == pytest.approx(3.02)
    assert len(results["ITD"].portfolio.breakdowns[Frequency.DAILY]) == 2
    assert results["ITD"].benchmark is None


def test_build_twr_results_by_period_filters_reset_events_to_period_window():
    results = _build_twr_results_by_period(
        performance_request=_twr_request(emit_resets=True),
        resolved_periods=[ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2))],
        freqs_by_period={"ITD": [Frequency.DAILY]},
        daily_results_df=_daily_twr_results_df(),
        engine_diagnostics=EngineDiagnostics(
            resets=[
                EngineResetEvent(date=date(2025, 1, 2), reason="in_period", impacted_rows=1),
                EngineResetEvent(date=date(2025, 1, 3), reason="outside_period", impacted_rows=1),
            ]
        ),
        benchmark_artifacts=None,
        benchmark_request=None,
        benchmark_input_mode=None,
        resolved_benchmark_id=None,
        benchmark_return_source=BenchmarkReturnSource.CALCULATED,
        master_start_date=date(2025, 1, 1),
    )

    reset_events = results["ITD"].reset_events
    assert reset_events is not None
    assert [event.reason for event in reset_events] == ["in_period"]


def test_twr_period_reset_events_respects_policy_and_period_window():
    diagnostics = EngineDiagnostics(
        resets=[
            EngineResetEvent(date=date(2025, 1, 2), reason="in_period", impacted_rows=1),
            EngineResetEvent(date=date(2025, 1, 3), reason="outside_period", impacted_rows=1),
        ]
    )
    period = ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2))

    disabled = _twr_period_reset_events(
        performance_request=_twr_request(emit_resets=False),
        engine_diagnostics=diagnostics,
        period=period,
    )
    enabled = _twr_period_reset_events(
        performance_request=_twr_request(emit_resets=True),
        engine_diagnostics=diagnostics,
        period=period,
    )

    assert disabled is None
    assert enabled is not None
    assert [event.reason for event in enabled] == ["in_period"]


def test_build_twr_portfolio_period_block_preserves_summary_and_breakdowns():
    request = _twr_request()
    daily_results_df = _daily_twr_results_df()
    period = ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2))

    portfolio = _build_twr_portfolio_period_block(
        performance_request=request,
        period=period,
        period_slice_df=daily_results_df.copy(),
        daily_results_df=daily_results_df,
        requested_frequencies=[Frequency.DAILY],
        breakdowns_data={Frequency.DAILY: []},
    )

    assert portfolio.summary.period_return.base == pytest.approx(3.02)
    assert portfolio.summary.cumulative_return is not None
    assert portfolio.summary.cumulative_return.base == pytest.approx(3.02)
    assert len(portfolio.breakdowns[Frequency.DAILY]) == 2


def test_build_twr_benchmark_period_blocks_projects_benchmark_identity_and_relative_return():
    benchmark_request = BenchmarkPerformanceRequest.model_validate(
        {
            "benchmark_id": "BMK-REQUESTED",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "benchmark_currency": "USD",
            "return_source": "vendor_series",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "benchmark_return_points": [
                {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                {"perf_date": "2025-01-02", "benchmark_return": 0.02},
            ],
        }
    )
    benchmark_daily_returns_df = pd.DataFrame(
        [
            {"date": date(2025, 1, 1), "benchmark_return": 0.01},
            {"date": date(2025, 1, 2), "benchmark_return": 0.02},
        ]
    )
    context = _TWRBenchmarkPeriodContext(
        artifacts=BenchmarkCalculationArtifacts(
            results_by_period={},
            daily_returns_df=benchmark_daily_returns_df,
            component_contributions_df=pd.DataFrame(),
            effective_period_start=date(2025, 1, 1),
            max_weight_sum_deviation=0.0,
            notes=[],
        ),
        request=benchmark_request,
        input_mode=BenchmarkInputMode.STATEFUL,
        resolved_benchmark_id="BMK-RESOLVED",
        return_source=BenchmarkReturnSource.VENDOR_SERIES,
        master_start_date=date(2025, 1, 1),
    )
    portfolio = ComparativeAnalyticsBlock(
        summary=ComparativeSummary(period_return={"base": 3.02}, cumulative_return={"base": 3.02}),
        breakdowns={},
    )

    benchmark, relative = _build_twr_benchmark_period_blocks(
        period=ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)),
        requested_frequencies=[],
        portfolio=portfolio,
        context=context,
    )

    assert benchmark is not None
    assert benchmark.benchmark_id == "BMK-RESOLVED"
    assert benchmark.input_mode == "stateful"
    assert benchmark.return_source == "vendor_series"
    assert benchmark.summary.period_return.base == pytest.approx(3.02)
    assert relative is not None
    assert relative.summary.period_return.base == pytest.approx(0.0)


def test_build_twr_response_model_preserves_envelope_metadata_and_supportability():
    request = _twr_request()
    resolved_period = ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2))
    daily_results_df = _daily_twr_results_df()
    calculation = _TWRExecutionCalculation(
        resolved_periods=[resolved_period],
        freqs_by_period={"ITD": [Frequency.DAILY]},
        master_start_date=resolved_period.start_date,
        master_end_date=resolved_period.end_date,
        daily_results_df=daily_results_df,
        engine_diagnostics=EngineDiagnostics(effective_period_start=date(2025, 1, 1)),
        benchmark_artifacts=None,
    )
    results_by_period = _build_twr_results_by_period(
        performance_request=request,
        resolved_periods=calculation.resolved_periods,
        freqs_by_period=calculation.freqs_by_period,
        daily_results_df=daily_results_df,
        engine_diagnostics=calculation.engine_diagnostics,
        benchmark_artifacts=None,
        benchmark_request=None,
        benchmark_input_mode=None,
        resolved_benchmark_id=None,
        benchmark_return_source=BenchmarkReturnSource.CALCULATED,
        master_start_date=calculation.master_start_date,
    )
    supportability = _resolve_twr_supportability(
        performance_request=request,
        results_by_period=results_by_period,
        daily_results_df=daily_results_df,
        benchmark_row_count=0,
    )

    response = _build_twr_response_model(
        performance_request=request,
        portfolio_id="P1",
        input_mode=TWRInputMode.STATELESS,
        input_fingerprint="fingerprint-1",
        calculation_hash="hash-1",
        engine_version="test-engine",
        calculation=calculation,
        results_by_period=results_by_period,
        benchmark_context=None,
        calculation_supportability=supportability,
    )

    assert response.calculation_id == request.calculation_id
    assert response.portfolio_id == "P1"
    assert response.calculation_supportability is supportability
    assert response.results_by_period == results_by_period
    assert response.meta.periods == {
        "requested": ["ITD"],
        "master_start": "2025-01-01",
        "master_end": "2025-01-02",
    }
    assert response.meta.input_fingerprint == "fingerprint-1"
    assert response.meta.calculation_hash == "hash-1"
    assert response.audit.counts == {"input_rows": 2}


def test_build_twr_lineage_details_includes_benchmark_artifacts():
    daily_results_df = _daily_twr_results_df()
    benchmark_daily_returns_df = pd.DataFrame(
        [
            {"date": date(2025, 1, 1), "benchmark_return": 0.01},
            {"date": date(2025, 1, 2), "benchmark_return": 0.02},
        ]
    )
    component_contributions_df = pd.DataFrame(
        [
            {
                "date": date(2025, 1, 1),
                "component_id": "EQ",
                "weight_bop": 1.0,
                "component_return": 0.01,
                "contribution": 0.01,
            }
        ]
    )
    benchmark_artifacts = BenchmarkCalculationArtifacts(
        results_by_period={},
        daily_returns_df=benchmark_daily_returns_df,
        component_contributions_df=component_contributions_df,
        effective_period_start=date(2025, 1, 1),
        max_weight_sum_deviation=0.0,
        notes=[],
    )

    execution_details, calculation_details = _build_twr_lineage_details(
        daily_results_df=daily_results_df,
        results_by_period=cast(dict[str, SinglePeriodPerformanceResult], {"ITD": object()}),
        benchmark_artifacts=benchmark_artifacts,
    )

    assert execution_details == {
        "periods_resolved": 1,
        "daily_rows": 2,
        "benchmark_daily_returns": 2,
        "benchmark_component_contributions": 1,
    }
    assert calculation_details["daily_results.csv"] is daily_results_df
    assert calculation_details["benchmark_daily_returns.csv"] is benchmark_daily_returns_df
    assert calculation_details["benchmark_component_contributions.csv"] is component_contributions_df


def test_as_numeric_returns_default_for_non_numeric_values():
    assert _as_numeric("not-a-number", default=7) == 7


def test_get_total_cum_ror_returns_zero_for_missing_row():
    assert _get_total_cum_ror(None, "local_ror_") == 0.0


def test_rebased_cumulative_ror_handles_standard_and_zero_start_denominators():
    assert _rebased_cumulative_ror(
        start_cumulative_ror=10.0,
        end_cumulative_ror=21.0,
    ) == pytest.approx(10.0)
    assert _rebased_cumulative_ror(
        start_cumulative_ror=-100.0,
        end_cumulative_ror=12.0,
    ) == pytest.approx(12.0)


def test_calculate_total_return_from_slice_returns_zero_for_empty_slice():
    empty_df = pd.DataFrame(
        columns=[
            PortfolioColumns.PERF_DATE.value,
            PortfolioColumns.PERF_RESET.value,
            PortfolioColumns.DAILY_ROR.value,
        ]
    )
    result = _calculate_total_return_from_slice(empty_df, empty_df)
    assert result.base == 0.0
    assert result.local == 0.0
    assert result.fx == 0.0


def test_calculate_total_return_from_slice_reset_handles_zero_base_denominator():
    full_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.FINAL_CUM_ROR.value: -100.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 0.0,
                "local_ror_short_cum_ror": 0.0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: True,
                PortfolioColumns.FINAL_CUM_ROR.value: 12.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 2.0,
                "local_ror_short_cum_ror": 3.0,
            },
        ]
    )
    period_slice = full_df[full_df[PortfolioColumns.PERF_DATE.value] == date(2025, 1, 2)]

    result = _calculate_total_return_from_slice(period_slice, full_df)
    assert result.base == pytest.approx(12.0)


def test_calculate_total_return_from_slice_reset_handles_zero_fx_denominator():
    full_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.FINAL_CUM_ROR.value: 0.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 0.0,
                "local_ror_short_cum_ror": 0.0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: True,
                PortfolioColumns.FINAL_CUM_ROR.value: 5.0,
                "local_ror": -100.0,
                "local_ror_long_cum_ror": -100.0,
                "local_ror_short_cum_ror": 0.0,
            },
        ]
    )
    period_slice = full_df[full_df[PortfolioColumns.PERF_DATE.value] == date(2025, 1, 2)]

    result = _calculate_total_return_from_slice(period_slice, full_df)
    assert result.local == pytest.approx(-100.0)
    assert result.fx == 0.0


def test_calculate_total_return_from_slice_reset_handles_zero_local_start_denominator():
    full_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.FINAL_CUM_ROR.value: 0.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": -100.0,
                "local_ror_short_cum_ror": 0.0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: True,
                PortfolioColumns.FINAL_CUM_ROR.value: 5.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 2.0,
                "local_ror_short_cum_ror": 3.0,
            },
        ]
    )
    period_slice = full_df[full_df[PortfolioColumns.PERF_DATE.value] == date(2025, 1, 2)]

    result = _calculate_total_return_from_slice(period_slice, full_df)
    expected_end_local = ((1 + 2.0 / 100) * (1 + 3.0 / 100) - 1) * 100
    assert result.local == pytest.approx(expected_end_local)


def test_calculate_total_return_from_slice_non_reset_handles_zero_fx_denominator():
    non_reset_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.DAILY_ROR.value: -100.0,
                "local_ror": -100.0,
            }
        ]
    )

    result = _calculate_total_return_from_slice(non_reset_df, non_reset_df)
    assert result.local == pytest.approx(-100.0)
    assert result.fx == 0.0
