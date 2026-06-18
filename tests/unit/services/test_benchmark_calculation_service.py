from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.services import benchmark_calculation_service
from common.enums import Frequency
from core.periods import ResolvedPeriod


def _calculated_request(*, include_timeseries: bool = True) -> BenchmarkPerformanceRequest:
    return BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily", "monthly"]}],
            "return_source": "calculated",
            "benchmark_currency": "USD",
            "output": {"include_timeseries": include_timeseries},
            "component_observations": [
                {
                    "component_id": "IDX_1",
                    "perf_date": "2025-01-01",
                    "weight_bop": 0.6,
                    "component_return": 0.01,
                    "component_return_local": 0.008,
                    "component_return_fx": 0.002,
                },
                {
                    "component_id": "IDX_2",
                    "perf_date": "2025-01-01",
                    "weight_bop": 0.4,
                    "component_return": 0.02,
                    "component_return_local": 0.015,
                    "component_return_fx": 0.005,
                },
            ],
        }
    )


def _vendor_request() -> BenchmarkPerformanceRequest:
    return BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily", "monthly"]}],
            "return_source": "vendor_series",
            "benchmark_currency": "USD",
            "output": {"include_timeseries": True},
            "benchmark_return_points": [
                {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                {"perf_date": "2025-01-02", "benchmark_return": 0.02},
            ],
        }
    )


def test_calculate_benchmark_artifacts_builds_calculated_period_results_with_optional_timeseries():
    request = _calculated_request(include_timeseries=True)

    artifacts = benchmark_calculation_service.calculate_benchmark_artifacts(request)

    assert artifacts.effective_period_start == date(2025, 1, 1)
    assert artifacts.max_weight_sum_deviation == 0.0
    assert artifacts.notes == []
    period_result = artifacts.results_by_period["ITD"]
    assert period_result.daily_returns is not None
    assert len(period_result.daily_returns) == 1
    assert period_result.component_contributions is not None
    assert len(period_result.component_contributions) == 2
    assert Frequency.DAILY in period_result.benchmark.breakdowns
    assert Frequency.MONTHLY in period_result.benchmark.breakdowns
    assert period_result.benchmark.summary.period_return.base == pytest.approx(1.4)
    assert period_result.benchmark.summary.period_return.local == pytest.approx(1.08)
    assert period_result.benchmark.summary.period_return.fx == pytest.approx(0.32)


def test_calculate_benchmark_artifacts_normalizes_mixed_date_like_artifact_rows(monkeypatch):
    request = _calculated_request(include_timeseries=True)

    monkeypatch.setattr(
        benchmark_calculation_service,
        "calculate_benchmark_returns",
        lambda component_observations: SimpleNamespace(
            daily_returns_df=pd.DataFrame(
                {
                    "date": [pd.Timestamp("2025-01-01T15:00:00Z"), "2025-01-02"],
                    "benchmark_return": [0.01, 0.02],
                    "benchmark_return_local": [0.008, 0.009],
                    "benchmark_return_fx": [0.002, 0.011],
                }
            ),
            component_contributions_df=pd.DataFrame(
                {
                    "date": ["2025-01-01", pd.Timestamp("2025-01-02T11:00:00Z")],
                    "component_id": ["IDX_1", "IDX_1"],
                    "weight_bop": [1.0, 1.0],
                    "component_return": [0.01, 0.02],
                    "contribution": [0.01, 0.02],
                }
            ),
            notes=[],
            effective_period_start=date(2025, 1, 1),
            max_weight_sum_deviation=0.0,
        ),
    )

    artifacts = benchmark_calculation_service.calculate_benchmark_artifacts(request)

    assert list(artifacts.daily_returns_df["date"]) == [date(2025, 1, 1), date(2025, 1, 2)]
    assert list(artifacts.component_contributions_df["date"]) == [date(2025, 1, 1), date(2025, 1, 2)]
    period_result = artifacts.results_by_period["ITD"]
    assert [row.date for row in period_result.daily_returns or []] == [date(2025, 1, 1), date(2025, 1, 2)]
    assert [row.date for row in period_result.component_contributions or []] == [
        date(2025, 1, 1),
        date(2025, 1, 2),
    ]


def test_calculate_benchmark_artifacts_omits_timeseries_when_not_requested():
    request = _calculated_request(include_timeseries=False)

    artifacts = benchmark_calculation_service.calculate_benchmark_artifacts(request)

    period_result = artifacts.results_by_period["ITD"]
    assert period_result.daily_returns is None
    assert period_result.component_contributions is None


def test_calculate_benchmark_artifacts_builds_vendor_series_results_and_skips_component_rows():
    request = _vendor_request()

    artifacts = benchmark_calculation_service.calculate_benchmark_artifacts(request)

    assert artifacts.effective_period_start == date(2025, 1, 1)
    assert artifacts.max_weight_sum_deviation == 0.0
    assert "vendor series" in artifacts.notes[0]
    assert artifacts.component_contributions_df.empty
    period_result = artifacts.results_by_period["ITD"]
    assert period_result.component_contributions is None
    assert period_result.daily_returns is not None
    assert len(period_result.daily_returns) == 2


def test_build_benchmark_source_artifacts_projects_vendor_series_inputs():
    request = _vendor_request()

    source_artifacts = benchmark_calculation_service._build_benchmark_source_artifacts(request)

    assert source_artifacts.effective_period_start == date(2025, 1, 1)
    assert source_artifacts.max_weight_sum_deviation == 0.0
    assert source_artifacts.component_contributions_df.empty
    assert source_artifacts.notes == [
        "Benchmark returns were sourced from vendor series because return_source=vendor_series was requested."
    ]
    assert list(source_artifacts.daily_returns_df["benchmark_return"]) == [Decimal("0.01"), Decimal("0.02")]


def test_normalize_benchmark_source_artifact_dates_handles_mixed_and_empty_component_rows():
    daily_returns_df = pd.DataFrame({"date": [pd.Timestamp("2025-01-01T15:00:00Z"), "2025-01-02"]})
    component_contributions_df = pd.DataFrame(columns=["date"])

    benchmark_calculation_service._normalize_benchmark_source_artifact_dates(
        daily_returns_df=daily_returns_df,
        component_contributions_df=component_contributions_df,
    )

    assert list(daily_returns_df["date"]) == [date(2025, 1, 1), date(2025, 1, 2)]
    assert component_contributions_df.empty


def test_calculate_benchmark_artifacts_skips_empty_period_slices(monkeypatch):
    request = _vendor_request()

    monkeypatch.setattr(
        benchmark_calculation_service,
        "resolve_periods",
        lambda periods, report_end_date, benchmark_start_date, explicit_start_date=None: [
            type("Period", (), {"name": "EMPTY", "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 2)})(),
            type("Period", (), {"name": "ITD", "start_date": date(2025, 1, 1), "end_date": date(2025, 1, 2)})(),
        ],
    )

    artifacts = benchmark_calculation_service.calculate_benchmark_artifacts(request)

    assert set(artifacts.results_by_period) == {"ITD"}


def test_benchmark_results_by_period_skips_empty_slices_and_preserves_frequency_selection():
    request = _vendor_request()
    daily_returns_df = pd.DataFrame(
        {
            "date": [date(2025, 1, 1), date(2025, 1, 2)],
            "benchmark_return": [0.01, 0.02],
        }
    )

    results = benchmark_calculation_service._benchmark_results_by_period(
        resolved_periods=[
            ResolvedPeriod(name="EMPTY", start_date=date(2024, 1, 1), end_date=date(2024, 1, 2)),
            ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)),
        ],
        daily_returns_df=daily_returns_df,
        component_contributions_df=pd.DataFrame(
            columns=["date", "component_id", "weight_bop", "component_return", "contribution"]
        ),
        benchmark_request=request,
        requested_frequencies_by_period={"ITD": [Frequency.DAILY]},
        input_mode="stateful",
    )

    assert set(results) == {"ITD"}
    assert results["ITD"].benchmark.input_mode == "stateful"
    assert set(results["ITD"].benchmark.breakdowns) == {Frequency.DAILY}


def test_benchmark_period_result_projects_timeseries_and_summary():
    request = _vendor_request()
    daily_returns_df = pd.DataFrame(
        {
            "date": [date(2025, 1, 1), date(2025, 1, 2)],
            "benchmark_return": [0.01, 0.02],
        }
    )
    component_contributions_df = pd.DataFrame(
        {
            "date": [date(2025, 1, 1)],
            "component_id": ["IDX_1"],
            "weight_bop": [1.0],
            "component_return": [0.01],
            "contribution": [0.01],
        }
    )

    result = benchmark_calculation_service._benchmark_period_result(
        period=ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)),
        daily_returns_df=daily_returns_df,
        component_contributions_df=component_contributions_df,
        benchmark_request=request,
        frequencies=[Frequency.DAILY],
        input_mode="stateless",
    )

    assert result is not None
    assert result.benchmark.summary.period_return.base == pytest.approx(3.02)
    assert result.benchmark.summary.cumulative_return.base == pytest.approx(3.02)
    assert result.benchmark.input_mode == "stateless"
    assert result.daily_returns is not None
    assert len(result.daily_returns) == 2
    assert result.component_contributions is not None
    assert len(result.component_contributions) == 1
    assert Frequency.DAILY in result.benchmark.breakdowns


def test_benchmark_period_result_returns_none_for_empty_window():
    request = _vendor_request()
    daily_returns_df = pd.DataFrame(
        {
            "date": [date(2025, 1, 1)],
            "benchmark_return": [0.01],
        }
    )

    result = benchmark_calculation_service._benchmark_period_result(
        period=ResolvedPeriod(name="EMPTY", start_date=date(2024, 1, 1), end_date=date(2024, 1, 2)),
        daily_returns_df=daily_returns_df,
        component_contributions_df=pd.DataFrame(),
        benchmark_request=request,
        frequencies=[Frequency.DAILY],
        input_mode=None,
    )

    assert result is None


def test_benchmark_period_timeseries_records_applies_output_and_empty_component_policy():
    period_daily_df = pd.DataFrame(
        {
            "date": [date(2025, 1, 1)],
            "benchmark_return": [0.01],
            "cumulative_return": [0.01],
        }
    )
    empty_component_df = pd.DataFrame(
        columns=["date", "component_id", "weight_bop", "component_return", "contribution"]
    )

    disabled_records = benchmark_calculation_service._benchmark_period_timeseries_records(
        period_daily_df=period_daily_df,
        period_component_df=empty_component_df,
        include_timeseries=False,
    )
    enabled_records = benchmark_calculation_service._benchmark_period_timeseries_records(
        period_daily_df=period_daily_df,
        period_component_df=empty_component_df,
        include_timeseries=True,
    )

    assert disabled_records.daily_returns is None
    assert disabled_records.component_contributions is None
    assert enabled_records.daily_returns is not None
    assert len(enabled_records.daily_returns) == 1
    assert enabled_records.component_contributions is None


def test_benchmark_period_daily_returns_sorts_links_and_suppresses_empty_windows():
    daily_returns_df = pd.DataFrame(
        {
            "date": [date(2025, 1, 2), date(2025, 1, 1)],
            "benchmark_return": [Decimal("0.02"), Decimal("0.01")],
        }
    )

    period_daily_df = benchmark_calculation_service._benchmark_period_daily_returns(
        period=ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)),
        daily_returns_df=daily_returns_df,
    )

    assert period_daily_df is not None
    assert list(period_daily_df["date"]) == [date(2025, 1, 1), date(2025, 1, 2)]
    assert list(period_daily_df["cumulative_return"]) == [Decimal("0.01"), Decimal("0.0302")]
    assert (
        benchmark_calculation_service._benchmark_period_daily_returns(
            period=ResolvedPeriod(name="EMPTY", start_date=date(2024, 1, 1), end_date=date(2024, 1, 2)),
            daily_returns_df=daily_returns_df,
        )
        is None
    )


def test_benchmark_calculation_helpers_cover_breakdown_and_scaling_edges():
    df = pd.DataFrame(
        {
            "date": [date(2025, 1, 1), date(2025, 1, 2)],
            "benchmark_return": [0.01, 0.02],
            "benchmark_return_local": [0.008, 0.009],
            "benchmark_return_fx": [0.002, 0.011],
            "cumulative_return": [0.01, 0.0302],
        }
    )

    comparative_value = benchmark_calculation_service._calculate_benchmark_return_from_slice(df)
    breakdowns = benchmark_calculation_service._build_benchmark_breakdowns(
        period_daily_df=df,
        frequencies=[Frequency.DAILY, Frequency.MONTHLY],
    )

    assert comparative_value.base == pytest.approx(3.02)
    assert comparative_value.local == pytest.approx(1.7072)
    assert comparative_value.fx == pytest.approx(1.3022)
    assert len(breakdowns[Frequency.DAILY]) == 2
    assert breakdowns[Frequency.MONTHLY][0].period == "2025-01"
    assert benchmark_calculation_service._scale_percent(None) is None
    assert benchmark_calculation_service._scale_percent("bad") is None
    assert benchmark_calculation_service._series_return(pd.Series([0.01, 0.02])) == pytest.approx(3.02)


def test_optional_benchmark_return_component_suppresses_missing_and_all_null_components():
    df = pd.DataFrame(
        {
            "benchmark_return": [0.01, 0.02],
            "benchmark_return_local": [None, None],
            "benchmark_return_fx": [0.001, 0.002],
        }
    )

    assert benchmark_calculation_service._optional_benchmark_return_component(df, "missing") is None
    assert benchmark_calculation_service._optional_benchmark_return_component(df, "benchmark_return_local") is None
    assert benchmark_calculation_service._optional_benchmark_return_component(
        df,
        "benchmark_return_fx",
    ) == pytest.approx(0.3002)


def test_benchmark_breakdowns_label_weekly_quarterly_and_yearly_periods():
    df = pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2025-01-03T10:00:00Z"),
                "2025-03-31",
                pd.Timestamp("2025-12-31T10:00:00Z"),
            ],
            "benchmark_return": [0.01, 0.02, 0.03],
            "benchmark_return_local": [0.01, 0.02, 0.03],
            "benchmark_return_fx": [0.0, 0.0, 0.0],
            "cumulative_return": [0.01, 0.0302, 0.061106],
        }
    )

    breakdowns = benchmark_calculation_service._build_benchmark_breakdowns(
        period_daily_df=df,
        frequencies=[Frequency.WEEKLY, Frequency.QUARTERLY, Frequency.YEARLY],
    )

    assert breakdowns[Frequency.WEEKLY][0].period == "2025-01-03"
    assert breakdowns[Frequency.QUARTERLY][0].period == "2025-Q1"
    assert breakdowns[Frequency.YEARLY][0].period == "2025"


def test_benchmark_breakdown_helpers_group_rows_and_format_labels():
    df = pd.DataFrame(
        {
            "date": [date(2025, 1, 1), date(2025, 1, 2), date(2025, 2, 3)],
            "benchmark_return": [0.01, 0.02, 0.03],
        }
    )
    sorted_df = df.sort_values("date").reset_index(drop=True)

    daily_groups = benchmark_calculation_service._group_benchmark_breakdown_rows(
        sorted_period_df=sorted_df,
        frequency=Frequency.DAILY,
    )
    monthly_groups = benchmark_calculation_service._group_benchmark_breakdown_rows(
        sorted_period_df=sorted_df,
        frequency=Frequency.MONTHLY,
    )
    item = benchmark_calculation_service._build_benchmark_breakdown_item(
        sorted_period_df=sorted_df,
        frequency_df=monthly_groups[0],
        frequency=Frequency.MONTHLY,
    )

    assert [len(group) for group in daily_groups] == [1, 1, 1]
    assert [group["date"].iloc[-1] for group in monthly_groups] == [date(2025, 1, 2), date(2025, 2, 3)]
    assert item.period == "2025-01"
    assert item.period_start == date(2025, 1, 1)
    assert item.period_end == date(2025, 1, 2)
    assert item.period_return.base == pytest.approx(3.02)
    assert item.cumulative_return.base == pytest.approx(3.02)
    assert (
        benchmark_calculation_service._benchmark_breakdown_label(
            frequency=Frequency.QUARTERLY,
            period_end=date(2025, 6, 30),
        )
        == "2025-Q2"
    )
    assert (
        benchmark_calculation_service._benchmark_breakdown_label(
            frequency=Frequency.YEARLY,
            period_end=date(2025, 12, 31),
        )
        == "2025"
    )


def test_benchmark_breakdown_group_helpers_project_daily_and_resampled_rows():
    df = pd.DataFrame(
        {
            "date": [date(2025, 1, 1), date(2025, 1, 2), date(2025, 2, 3)],
            "benchmark_return": [0.01, 0.02, 0.03],
        }
    )

    daily_rows = benchmark_calculation_service._daily_benchmark_breakdown_rows(df)
    monthly_rows = benchmark_calculation_service._resampled_benchmark_breakdown_rows(
        sorted_period_df=df,
        frequency=Frequency.MONTHLY,
    )

    assert [len(row) for row in daily_rows] == [1, 1, 1]
    assert [row["date"].iloc[-1] for row in monthly_rows] == [date(2025, 1, 2), date(2025, 2, 3)]


def test_calculate_benchmark_artifacts_supports_explicit_period_window():
    request = BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_EXPLICIT",
            "benchmark_start_date": "2025-01-01",
            "report_start_date": "2025-01-02",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "return_source": "calculated",
            "benchmark_currency": "USD",
            "output": {"include_timeseries": True},
            "component_observations": [
                {
                    "component_id": "IDX_1",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_return": 0.01,
                },
                {
                    "component_id": "IDX_1",
                    "perf_date": "2025-01-02",
                    "weight_bop": 1.0,
                    "component_return": 0.02,
                },
            ],
        }
    )

    artifacts = benchmark_calculation_service.calculate_benchmark_artifacts(request)

    explicit = artifacts.results_by_period["EXPLICIT"]
    assert explicit.benchmark.summary.period_return.base == pytest.approx(2.0)
    assert len(explicit.daily_returns or []) == 1
