from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from typing import Any, Iterable

import pandas as pd
from fastapi import HTTPException, status

from adapters.api_adapter import create_engine_config, create_engine_dataframe
from app.core.config import get_settings
from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.models.requests import PerformanceRequest
from app.models.returns_series import (
    CalendarPolicy,
    FillMethod,
    InputMode,
    MissingDataPolicy,
    ResolvedWindow,
    ReturnPoint,
    ReturnsDiagnostics,
    ReturnsFrequency,
    ReturnsMetadata,
    ReturnsProvenance,
    ReturnsRelativePeriod,
    ReturnsSeriesBenchmarkContext,
    ReturnsSeriesPayload,
    ReturnsSeriesRequest,
    ReturnsSeriesResponse,
    SeriesCoverage,
    SeriesGap,
)
from app.observability import correlation_id_var, request_id_var, trace_id_var
from app.services.analytics_numeric import numeric_value
from app.services.analytics_observation_dates import observation_timestamp_series
from app.services.error_details import (
    insufficient_data_detail,
    invalid_request_detail,
    resource_not_found_detail,
    source_unavailable_detail,
    upstream_contract_violation_detail,
)
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import (
    EXECUTION_STAGE_EXECUTION,
    EXECUTION_STAGE_NORMALIZATION,
    EXECUTION_STAGE_RETRIEVAL,
)
from app.services.portfolio_source_service import (
    build_stateful_input_service,
)
from app.services.service_identity import LOTUS_PERFORMANCE_CONSUMER_SYSTEM
from app.services.stateful_benchmark_input_service import build_stateful_benchmark_input
from app.services.stateful_performance_input_service import StatefulPortfolioInput, retrieve_stateful_portfolio_input
from app.services.stateful_retrieval_metadata import parse_zero_default_retrieval_metadata
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points
from common.enums import Frequency, PeriodType
from core.errors import HTTP_422_UNPROCESSABLE
from core.repro import generate_canonical_hash
from engine.benchmarks import benchmark_return_points_to_dataframe, calculate_benchmark_returns
from engine.compute import run_calculations
from engine.schema import PortfolioColumns

RETURN_POINT_QUANTUM = Decimal("0.000000000001")
_EXPECTED_RETURN_GAP_DAYS = {
    ReturnsFrequency.DAILY: 1,
    ReturnsFrequency.WEEKLY: 7,
    ReturnsFrequency.MONTHLY: 31,
}


@dataclass(frozen=True)
class ResolvedStatefulReturnsSeriesRequest:
    request: ReturnsSeriesRequest
    identity_payload: dict[str, Any]
    input_count: int
    resolved_benchmark_id: str | None
    resolved_benchmark_return_source: str | None
    benchmark_work_units: int


@dataclass(frozen=True)
class _ReturnsSeriesPointOutputs:
    portfolio_return_points: list[ReturnPoint]
    cumulative_portfolio_return_points: list[ReturnPoint] | None
    benchmark_return_points: list[ReturnPoint] | None
    cumulative_benchmark_return_points: list[ReturnPoint] | None
    risk_free_return_points: list[ReturnPoint] | None
    cumulative_risk_free_return_points: list[ReturnPoint] | None
    active_return_points: list[ReturnPoint] | None
    cumulative_active_return_points: list[ReturnPoint] | None


@dataclass(frozen=True)
class _ReturnsSeriesDiagnosticsResult:
    diagnostics: ReturnsDiagnostics
    requested_points: int
    returned_points: int


@dataclass(frozen=True)
class _ReturnsSeriesIdentity:
    input_fingerprint: str
    calculation_hash: str


@dataclass(frozen=True)
class _ReturnsSeriesExecutionContext:
    request: ReturnsSeriesRequest
    resolved_window: ResolvedWindow
    effective_input_mode: InputMode
    input_fingerprint: str
    calculation_hash: str
    resolved_benchmark_id: str | None
    resolved_benchmark_return_source: BenchmarkReturnSource


@dataclass(frozen=True)
class _StatefulBenchmarkSeriesSource:
    benchmark_points: list[dict[str, Any]]
    benchmark_source_details: dict[str, int]
    benchmark_work_units: int


@dataclass(frozen=True)
class _StatefulBenchmarkResolution:
    benchmark_id: str | None
    benchmark_points: list[dict[str, Any]] | None
    benchmark_df: pd.DataFrame | None
    benchmark_source_details: dict[str, int]
    benchmark_work_units: int


@dataclass(frozen=True)
class _StatefulReturnsSeriesFrames:
    portfolio_df: pd.DataFrame
    benchmark_df: pd.DataFrame | None
    risk_free_df: pd.DataFrame | None


@dataclass(frozen=True)
class _StatefulReturnsSeriesResolvedRequest:
    request: ReturnsSeriesRequest
    identity_payload: dict[str, Any]


_CALENDAR_PERIOD_START_FREQUENCIES: dict[ReturnsRelativePeriod, str] = {
    ReturnsRelativePeriod.MTD: "M",
    ReturnsRelativePeriod.QTD: "Q",
    ReturnsRelativePeriod.YTD: "Y",
}
_TRAILING_PERIOD_YEARS: dict[ReturnsRelativePeriod, int] = {
    ReturnsRelativePeriod.ONE_YEAR: 1,
    ReturnsRelativePeriod.THREE_YEAR: 3,
    ReturnsRelativePeriod.FIVE_YEAR: 5,
}


def _resolved_relative_period_start(as_of: pd.Timestamp, period: ReturnsRelativePeriod) -> date | None:
    calendar_frequency = _CALENDAR_PERIOD_START_FREQUENCIES.get(period)
    if calendar_frequency is not None:
        return as_of.to_period(calendar_frequency).start_time.date()

    trailing_years = _TRAILING_PERIOD_YEARS.get(period)
    if trailing_years is not None:
        return (as_of - pd.DateOffset(years=trailing_years) + pd.Timedelta(days=1)).date()

    if period == ReturnsRelativePeriod.SI:
        return date(1900, 1, 1)

    return None


def period_start(as_of_date: date, period: ReturnsRelativePeriod, year: int | None) -> date:
    as_of = pd.Timestamp(as_of_date)
    relative_start = _resolved_relative_period_start(as_of, period)
    if relative_start is not None:
        return relative_start
    if period == ReturnsRelativePeriod.YEAR:
        if year is None:
            raise ValueError("year is required when period=YEAR")
        return date(year, 1, 1)
    raise ValueError(f"Unsupported period: {period}")


def resolve_window(request: ReturnsSeriesRequest) -> ResolvedWindow:
    if request.window.mode.value == "EXPLICIT":
        return ResolvedWindow(
            start_date=request.window.from_date,
            end_date=request.window.to_date,
            resolved_period_label=None,
        )
    if request.window.period is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=invalid_request_detail("window.period is required when mode=RELATIVE"),
        )
    start_date = period_start(request.as_of_date, request.window.period, request.window.year)
    return ResolvedWindow(
        start_date=start_date,
        end_date=request.as_of_date,
        resolved_period_label=request.window.period.value,
    )


def to_dataframe(points: Iterable[ReturnPoint], *, series_type: str) -> pd.DataFrame:
    data = [{"date": p.date, "return_value": Decimal(str(p.return_value))} for p in points]
    df = pd.DataFrame(data)
    if df.empty:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=insufficient_data_detail(f"{series_type} series is empty."),
        )
    if df["date"].duplicated().any():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=invalid_request_detail(f"{series_type} series contains duplicate dates."),
        )
    df["date"] = _return_timestamp_series(df["date"])
    return df.sort_values("date")


def _return_timestamp_series(values: Iterable[object]) -> pd.Series:
    return observation_timestamp_series(values)


def _daily_return_percentage_to_ratio(value: object) -> Decimal | None:
    numeric = numeric_value(value, default=None)
    if numeric is None:
        return None
    return Decimal(str(numeric)) / Decimal("100")


def filter_window(df: pd.DataFrame, *, resolved_window: ResolvedWindow) -> pd.DataFrame:
    mask = (df["date"].dt.date >= resolved_window.start_date) & (df["date"].dt.date <= resolved_window.end_date)
    window_df = df[mask].copy()
    if window_df.empty:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=insufficient_data_detail("No observations in resolved window."),
        )
    return window_df


def resample_returns(df: pd.DataFrame, *, frequency: ReturnsFrequency) -> pd.DataFrame:
    if frequency == ReturnsFrequency.DAILY:
        return df
    indexed = df.set_index("date")
    if frequency == ReturnsFrequency.WEEKLY:
        grouped = indexed["return_value"].resample("W-FRI").apply(lambda x: (1 + x).prod() - 1)
    else:
        grouped = indexed["return_value"].resample("ME").apply(lambda x: (1 + x).prod() - 1)
    return grouped.dropna().reset_index()


def apply_calendar_policy(
    df: pd.DataFrame,
    *,
    frequency: ReturnsFrequency,
    calendar_policy: CalendarPolicy,
) -> pd.DataFrame:
    if frequency != ReturnsFrequency.DAILY or calendar_policy == CalendarPolicy.CALENDAR:
        return df
    return df[df["date"].dt.weekday < 5].copy()


def date_range_count(
    resolved_window: ResolvedWindow, *, frequency: ReturnsFrequency, calendar_policy: CalendarPolicy
) -> int:
    start = pd.Timestamp(resolved_window.start_date)
    end = pd.Timestamp(resolved_window.end_date)
    if frequency == ReturnsFrequency.DAILY:
        if calendar_policy == CalendarPolicy.CALENDAR:
            return len(pd.date_range(start, end, freq="D"))
        return len(pd.bdate_range(start, end))
    if frequency == ReturnsFrequency.WEEKLY:
        return len(pd.date_range(start, end, freq="W-FRI"))
    return len(pd.date_range(start, end, freq="ME"))


def _missing_return_gap_days(
    prev: date,
    curr: date,
    *,
    frequency: ReturnsFrequency,
    calendar_policy: CalendarPolicy,
) -> int:
    if frequency == ReturnsFrequency.DAILY and calendar_policy != CalendarPolicy.CALENDAR:
        return max(len(pd.bdate_range(pd.Timestamp(prev), pd.Timestamp(curr))) - 2, 0)
    delta = (curr - prev).days
    if delta <= _EXPECTED_RETURN_GAP_DAYS[frequency] + 1:
        return 0
    return delta - 1


def detect_gaps(
    df: pd.DataFrame,
    *,
    frequency: ReturnsFrequency,
    series_type: str,
    calendar_policy: CalendarPolicy = CalendarPolicy.CALENDAR,
) -> list[SeriesGap]:
    if len(df) < 2:
        return []
    gaps: list[SeriesGap] = []
    dates = list(df["date"].dt.date)
    for prev, curr in zip(dates, dates[1:]):
        gap_days = _missing_return_gap_days(
            prev,
            curr,
            frequency=frequency,
            calendar_policy=calendar_policy,
        )
        if gap_days > 0:
            gaps.append(SeriesGap(series_type=series_type, from_date=prev, to_date=curr, gap_days=gap_days))
    return gaps


def points_from_df(df: pd.DataFrame) -> list[ReturnPoint]:
    out: list[ReturnPoint] = []
    for _, row in df.iterrows():
        value = _quantize_return_point_decimal(Decimal(str(row["return_value"])))
        out.append(ReturnPoint(date=row["date"].date(), return_value=value))
    return out


def build_cumulative_return_points(df: pd.DataFrame | None) -> list[ReturnPoint] | None:
    if df is None or df.empty:
        return None
    running = Decimal("1")
    cumulative_points: list[ReturnPoint] = []
    for _, row in df.sort_values("date").iterrows():
        running *= Decimal("1") + Decimal(str(row["return_value"]))
        cumulative_points.append(
            ReturnPoint(
                date=row["date"].date(),
                return_value=_quantize_return_point_decimal(running - Decimal("1")),
            )
        )
    return cumulative_points


def _quantize_return_point_decimal(value: Decimal) -> Decimal:
    if value == 0:
        return Decimal("0").quantize(RETURN_POINT_QUANTUM)
    with localcontext() as context:
        context.prec = max(28, value.adjusted() + 16)
        return value.quantize(RETURN_POINT_QUANTUM)


def build_active_return_points(
    *,
    portfolio_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
) -> list[ReturnPoint] | None:
    if benchmark_df is None:
        return None

    aligned_df = (
        portfolio_df[["date", "return_value"]]
        .merge(
            benchmark_df[["date", "return_value"]],
            on="date",
            how="inner",
            suffixes=("_portfolio", "_benchmark"),
        )
        .sort_values("date")
    )
    if aligned_df.empty:
        return None

    portfolio_values = [Decimal(str(value)) for value in aligned_df["return_value_portfolio"]]
    benchmark_values = [Decimal(str(value)) for value in aligned_df["return_value_benchmark"]]
    active_df = pd.DataFrame(
        {
            "date": aligned_df["date"],
            "return_value": [
                portfolio_value - benchmark_value
                for portfolio_value, benchmark_value in zip(portfolio_values, benchmark_values, strict=True)
            ],
        }
    )
    return points_from_df(active_df)


def build_cumulative_active_return_points(
    *,
    portfolio_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
) -> list[ReturnPoint] | None:
    if benchmark_df is None:
        return None

    cumulative_portfolio = build_cumulative_return_points(portfolio_df)
    cumulative_benchmark = build_cumulative_return_points(benchmark_df)
    if cumulative_portfolio is None or cumulative_benchmark is None:
        return None

    portfolio_df_aligned = to_dataframe(cumulative_portfolio, series_type="portfolio_cumulative")
    benchmark_df_aligned = to_dataframe(cumulative_benchmark, series_type="benchmark_cumulative")
    aligned_df = (
        portfolio_df_aligned[["date", "return_value"]]
        .merge(
            benchmark_df_aligned[["date", "return_value"]],
            on="date",
            how="inner",
            suffixes=("_portfolio", "_benchmark"),
        )
        .sort_values("date")
    )
    if aligned_df.empty:
        return None

    active_df = pd.DataFrame(
        {
            "date": aligned_df["date"],
            "return_value": [
                Decimal(str(portfolio_value)) - Decimal(str(benchmark_value))
                for portfolio_value, benchmark_value in zip(
                    aligned_df["return_value_portfolio"],
                    aligned_df["return_value_benchmark"],
                    strict=True,
                )
            ],
        }
    )
    return points_from_df(active_df)


def core_frequency_label(_frequency: ReturnsFrequency) -> str:
    return "daily"


def core_points_to_dataframe(
    *,
    points: list[dict[str, Any]],
    date_key: str,
    value_key: str,
    series_type: str,
) -> pd.DataFrame:
    normalized_points: list[ReturnPoint] = []
    for point in points:
        date_raw = point.get(date_key)
        value_raw = point.get(value_key)
        if not isinstance(date_raw, str) or value_raw is None:
            continue
        try:
            normalized_points.append(
                ReturnPoint(date=date.fromisoformat(date_raw), return_value=Decimal(str(value_raw)))
            )
        except (ValueError, ArithmeticError):
            continue
    return to_dataframe(normalized_points, series_type=series_type)


def daily_ror_from_portfolio_timeseries(
    *,
    observations: list[dict[str, object]],
    performance_start_date: date,
    resolved_window: ResolvedWindow,
    metric_basis: str,
) -> pd.DataFrame:
    valuation_points = portfolio_timeseries_to_valuation_points(observations=observations)
    request_model = PerformanceRequest.model_validate(
        {
            "portfolio_id": "INTEGRATION_SERIES",
            "performance_start_date": performance_start_date,
            "metric_basis": metric_basis,
            "report_start_date": resolved_window.start_date,
            "report_end_date": resolved_window.end_date,
            "analyses": [{"period": PeriodType.EXPLICIT, "frequencies": [Frequency.DAILY]}],
            "valuation_points": valuation_points,
        }
    )
    config = create_engine_config(request_model, resolved_window.start_date, resolved_window.end_date)
    engine_df = create_engine_dataframe([point for point in valuation_points])
    daily_results_df, _ = run_calculations(engine_df, config)
    if daily_results_df.empty:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=insufficient_data_detail("No portfolio return observations in resolved window."),
        )
    output_df = pd.DataFrame(
        {
            "date": _return_timestamp_series(daily_results_df[PortfolioColumns.PERF_DATE.value]),
            "return_value": [
                _daily_return_percentage_to_ratio(value) for value in daily_results_df[PortfolioColumns.DAILY_ROR.value]
            ],
        }
    )
    output_df = output_df.dropna(subset=["return_value"]).sort_values("date")
    if output_df.empty:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=insufficient_data_detail("No valid portfolio return observations after normalization."),
        )
    return output_df


def fail_execution(*, calculation_id, message: str, active_stage: str | None) -> None:
    if active_stage is not None:
        execution_registry.fail_stage(calculation_id, active_stage, message)
    execution_registry.mark_failed(calculation_id, message)


def _build_stateful_resolved_returns_payload(
    *,
    request: ReturnsSeriesRequest,
    resolved_window: ResolvedWindow,
    portfolio_records: list[dict[str, str]],
    benchmark_records: list[dict[str, str]] | None,
    risk_free_records: list[dict[str, str]] | None,
    resolved_benchmark_id: str | None,
    resolved_benchmark_return_source: str | None,
) -> dict[str, Any]:
    return {
        "portfolio_id": request.portfolio_id,
        "as_of_date": str(request.as_of_date),
        "resolved_window": {
            "start_date": str(resolved_window.start_date),
            "end_date": str(resolved_window.end_date),
            "resolved_period_label": resolved_window.resolved_period_label,
        },
        "frequency": request.frequency.value,
        "metric_basis": request.metric_basis.value,
        "reporting_currency": request.reporting_currency,
        "series_selection": request.series_selection.model_dump(mode="json"),
        "benchmark": (
            {
                "benchmark_id": resolved_benchmark_id,
                "return_source": resolved_benchmark_return_source,
            }
            if resolved_benchmark_id
            else None
        ),
        "risk_free": request.risk_free.model_dump(mode="json") if request.risk_free is not None else None,
        "data_policy": request.data_policy.model_dump(mode="json"),
        "input_mode": InputMode.STATELESS.value,
        "stateless_input": {
            "portfolio_returns": portfolio_records,
            "benchmark_returns": benchmark_records,
            "risk_free_returns": risk_free_records,
        },
    }


def _records_from_points(points: list[ReturnPoint] | None) -> list[dict[str, str]] | None:
    if points is None:
        return None
    return [
        {
            "date": point.date.isoformat(),
            "return_value": format(point.return_value, "f"),
        }
        for point in points
    ]


def _get_requested_benchmark_return_source(request: ReturnsSeriesRequest) -> BenchmarkReturnSource:
    if request.benchmark is not None:
        return request.benchmark.return_source
    return BenchmarkReturnSource.CALCULATED


def _benchmark_daily_returns_to_dataframe(daily_returns_df: pd.DataFrame) -> pd.DataFrame:
    if daily_returns_df.empty:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=insufficient_data_detail("Benchmark series is empty."),
        )
    benchmark_df = daily_returns_df[["date", "benchmark_return"]].copy()
    benchmark_df["date"] = _return_timestamp_series(benchmark_df["date"])
    benchmark_df = benchmark_df.rename(columns={"benchmark_return": "return_value"}).sort_values("date")
    if benchmark_df["date"].duplicated().any():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=invalid_request_detail("benchmark series contains duplicate dates."),
        )
    return benchmark_df


def _risk_free_day_count_denominator(day_count_convention: object) -> Decimal:
    convention = str(day_count_convention or "ACT_360").upper()
    if convention in {"ACT_365", "ACT/365"}:
        return Decimal("365")
    if convention in {"30_360", "30/360", "ACT_360", "ACT/360"}:
        return Decimal("360")
    return Decimal("360")


def _risk_free_return_point_from_source(point: dict[str, Any]) -> ReturnPoint | None:
    date_raw = point.get("series_date")
    value_raw = point.get("value")
    if not isinstance(date_raw, str) or value_raw is None:
        return None
    try:
        return_value = Decimal(str(value_raw))
        if str(point.get("value_convention") or "").lower() == "annualized_rate":
            return_value = return_value / _risk_free_day_count_denominator(point.get("day_count_convention"))
        return ReturnPoint(date=date.fromisoformat(date_raw), return_value=return_value)
    except (ValueError, ArithmeticError):
        return None


def risk_free_points_to_dataframe(*, points: list[dict[str, Any]]) -> pd.DataFrame:
    normalized_points = [
        normalized_point
        for point in points
        if (normalized_point := _risk_free_return_point_from_source(point)) is not None
    ]
    return to_dataframe(normalized_points, series_type="risk_free")


def _selected_series_common_dates(
    *,
    portfolio_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    risk_free_df: pd.DataFrame | None,
) -> set[Any]:
    common_dates = set(portfolio_df["date"])
    for selected_df in (benchmark_df, risk_free_df):
        if selected_df is not None:
            common_dates &= set(selected_df["date"])
    return common_dates


def _apply_strict_intersection_policy(
    *,
    portfolio_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    risk_free_df: pd.DataFrame | None,
    missing_data_policy: MissingDataPolicy,
) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None]:
    if missing_data_policy != MissingDataPolicy.STRICT_INTERSECTION:
        return portfolio_df, benchmark_df, risk_free_df

    common_dates = _selected_series_common_dates(
        portfolio_df=portfolio_df,
        benchmark_df=benchmark_df,
        risk_free_df=risk_free_df,
    )
    if not common_dates:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=insufficient_data_detail("No overlapping dates across selected series."),
        )

    portfolio_df = portfolio_df[portfolio_df["date"].isin(common_dates)].sort_values("date")
    if benchmark_df is not None:
        benchmark_df = benchmark_df[benchmark_df["date"].isin(common_dates)].sort_values("date")
    if risk_free_df is not None:
        risk_free_df = risk_free_df[risk_free_df["date"].isin(common_dates)].sort_values("date")
    return portfolio_df, benchmark_df, risk_free_df


def _fill_optional_series_to_portfolio_dates(
    *,
    selected_df: pd.DataFrame | None,
    portfolio_dates: pd.Series,
    fill_method: FillMethod,
) -> pd.DataFrame | None:
    if selected_df is None:
        return None
    if fill_method == FillMethod.FORWARD_FILL:
        return selected_df.set_index("date").reindex(portfolio_dates).ffill().reset_index()
    if fill_method == FillMethod.ZERO_FILL:
        return selected_df.set_index("date").reindex(portfolio_dates).fillna(0.0).reset_index()
    return selected_df


def _apply_selected_fill_method(
    *,
    portfolio_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    risk_free_df: pd.DataFrame | None,
    fill_method: FillMethod,
) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None]:
    portfolio_dates = portfolio_df["date"]
    benchmark_df = _fill_optional_series_to_portfolio_dates(
        selected_df=benchmark_df,
        portfolio_dates=portfolio_dates,
        fill_method=fill_method,
    )
    risk_free_df = _fill_optional_series_to_portfolio_dates(
        selected_df=risk_free_df,
        portfolio_dates=portfolio_dates,
        fill_method=fill_method,
    )
    return portfolio_df, benchmark_df, risk_free_df


def _returns_series_input_dataframe(
    *,
    points: list[ReturnPoint],
    series_type: str,
    resolved_window: ResolvedWindow,
    frequency: ReturnsFrequency,
    calendar_policy: CalendarPolicy,
) -> pd.DataFrame:
    series_df = resample_returns(
        filter_window(
            to_dataframe(points, series_type=series_type),
            resolved_window=resolved_window,
        ),
        frequency=frequency,
    )
    return apply_calendar_policy(
        series_df,
        frequency=frequency,
        calendar_policy=calendar_policy,
    )


def _prepare_stateless_returns_series_dataframes(
    *,
    request: ReturnsSeriesRequest,
    resolved_window: ResolvedWindow,
) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None]:
    stateless_input = request.stateless_input
    if stateless_input is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=invalid_request_detail("stateless_input is required in stateless mode."),
        )

    portfolio_df = _returns_series_input_dataframe(
        points=stateless_input.portfolio_returns,
        series_type="portfolio",
        resolved_window=resolved_window,
        frequency=request.frequency,
        calendar_policy=request.data_policy.calendar_policy,
    )
    benchmark_df = (
        _returns_series_input_dataframe(
            points=stateless_input.benchmark_returns or [],
            series_type="benchmark",
            resolved_window=resolved_window,
            frequency=request.frequency,
            calendar_policy=request.data_policy.calendar_policy,
        )
        if request.series_selection.include_benchmark
        else None
    )
    risk_free_df = (
        _returns_series_input_dataframe(
            points=stateless_input.risk_free_returns or [],
            series_type="risk_free",
            resolved_window=resolved_window,
            frequency=request.frequency,
            calendar_policy=request.data_policy.calendar_policy,
        )
        if request.series_selection.include_risk_free
        else None
    )
    return portfolio_df, benchmark_df, risk_free_df


def _build_stateful_returns_series_frames(
    *,
    request: ReturnsSeriesRequest,
    resolved_window: ResolvedWindow,
    observations: list[dict[str, object]],
    portfolio_performance_start_date: date,
    benchmark_points: list[dict[str, Any]] | None,
    benchmark_df: pd.DataFrame | None,
    risk_free_points: list[dict[str, Any]] | None,
) -> _StatefulReturnsSeriesFrames:
    portfolio_df = resample_returns(
        daily_ror_from_portfolio_timeseries(
            observations=observations,
            performance_start_date=portfolio_performance_start_date,
            resolved_window=resolved_window,
            metric_basis=request.metric_basis.value,
        ),
        frequency=request.frequency,
    )
    resolved_benchmark_df = benchmark_df
    if benchmark_points is not None:
        resolved_benchmark_df = resample_returns(
            filter_window(
                core_points_to_dataframe(
                    points=benchmark_points,
                    date_key="series_date",
                    value_key="benchmark_return",
                    series_type="benchmark",
                ),
                resolved_window=resolved_window,
            ),
            frequency=request.frequency,
        )

    risk_free_df: pd.DataFrame | None = None
    if risk_free_points is not None:
        risk_free_df = resample_returns(
            filter_window(
                risk_free_points_to_dataframe(points=risk_free_points),
                resolved_window=resolved_window,
            ),
            frequency=request.frequency,
        )
    return _StatefulReturnsSeriesFrames(
        portfolio_df=portfolio_df,
        benchmark_df=resolved_benchmark_df,
        risk_free_df=risk_free_df,
    )


def _stateful_returns_retrieval_stage_details(
    *,
    observations: list[dict[str, object]],
    portfolio_source: StatefulPortfolioInput,
    benchmark_resolution: _StatefulBenchmarkResolution,
    risk_free_points: list[dict[str, Any]] | None,
    risk_free_payload: dict[str, Any] | None,
) -> dict[str, int]:
    risk_free_retrieval = (
        parse_zero_default_retrieval_metadata(risk_free_payload) if risk_free_points is not None else None
    )
    return {
        "portfolio_observations": len(observations),
        "benchmark_points": benchmark_resolution.benchmark_source_details.get(
            "benchmark_points",
            len(benchmark_resolution.benchmark_points or []),
        ),
        "benchmark_work_units": benchmark_resolution.benchmark_work_units,
        "risk_free_points": len(risk_free_points or []),
        "portfolio_chunk_count": portfolio_source.retrieval_metadata.chunk_count,
        "portfolio_page_count": portfolio_source.retrieval_metadata.page_count,
        "benchmark_chunk_count": benchmark_resolution.benchmark_source_details.get("benchmark_chunk_count", 0),
        "benchmark_page_count": benchmark_resolution.benchmark_source_details.get("benchmark_page_count", 0),
        "risk_free_chunk_count": risk_free_retrieval.chunk_count if risk_free_retrieval is not None else 0,
    }


def _stateful_returns_normalization_stage_details(
    *,
    portfolio_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    risk_free_df: pd.DataFrame | None,
) -> dict[str, int]:
    return {
        "portfolio_points": len(portfolio_df),
        "benchmark_points": len(benchmark_df) if benchmark_df is not None else 0,
        "risk_free_points": len(risk_free_df) if risk_free_df is not None else 0,
    }


def _build_resolved_stateful_returns_series_request(
    *,
    request: ReturnsSeriesRequest,
    resolved_window: ResolvedWindow,
    observations: list[dict[str, object]],
    portfolio_performance_start_date: date,
    benchmark_resolution: _StatefulBenchmarkResolution,
    risk_free_points: list[dict[str, Any]] | None,
    resolved_benchmark_id: str | None,
    resolved_benchmark_return_source: BenchmarkReturnSource,
) -> _StatefulReturnsSeriesResolvedRequest:
    normalized_frames = _build_stateful_returns_series_frames(
        request=request,
        resolved_window=resolved_window,
        observations=observations,
        portfolio_performance_start_date=portfolio_performance_start_date,
        benchmark_points=benchmark_resolution.benchmark_points,
        benchmark_df=benchmark_resolution.benchmark_df,
        risk_free_points=risk_free_points,
    )
    portfolio_df = normalized_frames.portfolio_df
    benchmark_df = normalized_frames.benchmark_df
    risk_free_df = normalized_frames.risk_free_df
    execution_registry.complete_stage(
        request.calculation_id,
        EXECUTION_STAGE_NORMALIZATION,
        details=_stateful_returns_normalization_stage_details(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
            risk_free_df=risk_free_df,
        ),
    )

    portfolio_return_points = points_from_df(portfolio_df)
    benchmark_return_points = points_from_df(benchmark_df) if benchmark_df is not None else None
    risk_free_return_points = points_from_df(risk_free_df) if risk_free_df is not None else None
    identity_payload = _build_stateful_resolved_returns_payload(
        request=request,
        resolved_window=resolved_window,
        portfolio_records=_records_from_points(portfolio_return_points) or [],
        benchmark_records=_records_from_points(benchmark_return_points),
        risk_free_records=_records_from_points(risk_free_return_points),
        resolved_benchmark_id=resolved_benchmark_id,
        resolved_benchmark_return_source=(resolved_benchmark_return_source.value if resolved_benchmark_id else None),
    )
    resolved_request = ReturnsSeriesRequest.model_validate(
        _resolved_stateful_returns_series_request_payload(request=request, identity_payload=identity_payload)
    )
    return _StatefulReturnsSeriesResolvedRequest(
        request=resolved_request,
        identity_payload=identity_payload,
    )


def _resolved_stateful_returns_series_request_payload(
    *,
    request: ReturnsSeriesRequest,
    identity_payload: dict[str, Any],
) -> dict[str, Any]:
    stateless_input = identity_payload["stateless_input"]
    return {
        "calculation_id": str(request.calculation_id),
        "portfolio_id": request.portfolio_id,
        "as_of_date": request.as_of_date.isoformat(),
        "window": request.window.model_dump(mode="json"),
        "frequency": request.frequency.value,
        "metric_basis": request.metric_basis.value,
        "reporting_currency": request.reporting_currency,
        "series_selection": request.series_selection.model_dump(mode="json"),
        "risk_free": request.risk_free.model_dump(mode="json") if request.risk_free is not None else None,
        "data_policy": request.data_policy.model_dump(mode="json"),
        "input_mode": InputMode.STATELESS.value,
        "stateless_input": {
            "portfolio_returns": stateless_input["portfolio_returns"],
            "benchmark_returns": stateless_input["benchmark_returns"],
            "risk_free_returns": stateless_input["risk_free_returns"],
        },
    }


def _benchmark_id_from_assignment_payload(assignment_payload: dict[str, Any]) -> str:
    benchmark_id_raw = assignment_payload.get("benchmark_id")
    benchmark_id = str(benchmark_id_raw) if benchmark_id_raw else None
    if not benchmark_id:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=upstream_contract_violation_detail("Benchmark assignment payload missing benchmark_id."),
        )
    return benchmark_id


async def _resolve_stateful_returns_series_benchmark_id(
    *,
    request: ReturnsSeriesRequest,
    stateful_input_service: Any,
    resolved_benchmark_id: str | None,
) -> str | None:
    if not request.series_selection.include_benchmark or resolved_benchmark_id:
        return resolved_benchmark_id

    assignment_status, assignment_payload = await stateful_input_service.get_benchmark_assignment(
        portfolio_id=request.portfolio_id,
        as_of_date=request.as_of_date,
        reporting_currency=request.reporting_currency,
    )
    if assignment_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=resource_not_found_detail("No benchmark assignment found for portfolio."),
        )
    if assignment_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=source_unavailable_detail(f"Benchmark assignment source unavailable ({assignment_status})."),
        )
    return _benchmark_id_from_assignment_payload(assignment_payload)


async def _retrieve_stateful_returns_series_risk_free(
    *,
    request: ReturnsSeriesRequest,
    stateful_input_service: Any,
    resolved_window: ResolvedWindow,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    if not request.series_selection.include_risk_free:
        return None, None
    if not request.reporting_currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=invalid_request_detail("reporting_currency is required for risk-free series in stateful mode."),
        )

    risk_free_status, risk_free_payload = await stateful_input_service.get_risk_free_series(
        currency=request.reporting_currency,
        as_of_date=request.as_of_date,
        start_date=resolved_window.start_date,
        end_date=resolved_window.end_date,
        frequency=core_frequency_label(request.frequency),
        series_mode="return_series",
        calculation_id=request.calculation_id,
    )
    if risk_free_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=resource_not_found_detail(f"No risk-free series found for {request.reporting_currency}."),
        )
    if risk_free_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=source_unavailable_detail(f"Risk-free series source unavailable ({risk_free_status})."),
        )

    risk_free_points = risk_free_payload.get("points")
    if not isinstance(risk_free_points, list):
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=upstream_contract_violation_detail("Risk-free series payload missing points list."),
        )
    return risk_free_points, risk_free_payload


async def _retrieve_stateful_returns_series_vendor_benchmark(
    *,
    request: ReturnsSeriesRequest,
    stateful_input_service: Any,
    resolved_window: ResolvedWindow,
    benchmark_id: str,
) -> _StatefulBenchmarkSeriesSource:
    benchmark_status, benchmark_payload = await stateful_input_service.get_benchmark_return_series(
        benchmark_id=benchmark_id,
        as_of_date=request.as_of_date,
        start_date=resolved_window.start_date,
        end_date=resolved_window.end_date,
        frequency=core_frequency_label(request.frequency),
        calculation_id=request.calculation_id,
    )
    if benchmark_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=resource_not_found_detail(f"No benchmark return series for {benchmark_id}."),
        )
    if benchmark_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=source_unavailable_detail(f"Benchmark return-series source unavailable ({benchmark_status})."),
        )
    benchmark_points = benchmark_payload.get("points")
    if not isinstance(benchmark_points, list):
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=upstream_contract_violation_detail("Benchmark return-series payload missing points list."),
        )
    benchmark_retrieval_metadata = parse_zero_default_retrieval_metadata(benchmark_payload)
    return _StatefulBenchmarkSeriesSource(
        benchmark_points=benchmark_points,
        benchmark_source_details={
            "benchmark_points": len(benchmark_points),
            "benchmark_chunk_count": benchmark_retrieval_metadata.chunk_count,
            "benchmark_page_count": benchmark_retrieval_metadata.page_count,
        },
        benchmark_work_units=len(benchmark_points),
    )


async def _resolve_stateful_returns_series_benchmark_source(
    *,
    request: ReturnsSeriesRequest,
    stateful_input_service: Any,
    resolved_window: ResolvedWindow,
    resolved_benchmark_id: str | None,
    resolved_benchmark_return_source: BenchmarkReturnSource,
) -> _StatefulBenchmarkResolution:
    benchmark_id = await _resolve_stateful_returns_series_benchmark_id(
        request=request,
        stateful_input_service=stateful_input_service,
        resolved_benchmark_id=resolved_benchmark_id,
    )
    if not request.series_selection.include_benchmark or not benchmark_id:
        return _StatefulBenchmarkResolution(
            benchmark_id=benchmark_id,
            benchmark_points=None,
            benchmark_df=None,
            benchmark_source_details={},
            benchmark_work_units=0,
        )

    if resolved_benchmark_return_source == BenchmarkReturnSource.VENDOR_SERIES:
        benchmark_source = await _retrieve_stateful_returns_series_vendor_benchmark(
            request=request,
            stateful_input_service=stateful_input_service,
            resolved_window=resolved_window,
            benchmark_id=benchmark_id,
        )
        return _StatefulBenchmarkResolution(
            benchmark_id=benchmark_id,
            benchmark_points=benchmark_source.benchmark_points,
            benchmark_df=None,
            benchmark_source_details=benchmark_source.benchmark_source_details,
            benchmark_work_units=benchmark_source.benchmark_work_units,
        )

    normalized_benchmark_input = await build_stateful_benchmark_input(
        stateful_input_service=stateful_input_service,
        calculation_id=request.calculation_id,
        benchmark_id=benchmark_id,
        as_of_date=request.as_of_date,
        start_date=resolved_window.start_date,
        end_date=resolved_window.end_date,
        return_source=resolved_benchmark_return_source,
    )
    benchmark_input_df = (
        calculate_benchmark_returns(normalized_benchmark_input.component_observations).daily_returns_df
        if resolved_benchmark_return_source == BenchmarkReturnSource.CALCULATED
        else benchmark_return_points_to_dataframe(normalized_benchmark_input.benchmark_return_points)
    )
    benchmark_df = resample_returns(
        filter_window(
            _benchmark_daily_returns_to_dataframe(benchmark_input_df),
            resolved_window=resolved_window,
        ),
        frequency=request.frequency,
    )
    benchmark_source_details = {
        **normalized_benchmark_input.source_details,
        "benchmark_points": len(benchmark_df),
    }
    return _StatefulBenchmarkResolution(
        benchmark_id=benchmark_id,
        benchmark_points=None,
        benchmark_df=benchmark_df,
        benchmark_source_details=benchmark_source_details,
        benchmark_work_units=normalized_benchmark_input.source_details.get(
            "component_observations",
            len(benchmark_df),
        ),
    )


def _build_returns_series_point_outputs(
    *,
    portfolio_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    risk_free_df: pd.DataFrame | None,
) -> _ReturnsSeriesPointOutputs:
    return _ReturnsSeriesPointOutputs(
        portfolio_return_points=points_from_df(portfolio_df),
        cumulative_portfolio_return_points=build_cumulative_return_points(portfolio_df),
        benchmark_return_points=points_from_df(benchmark_df) if benchmark_df is not None else None,
        cumulative_benchmark_return_points=build_cumulative_return_points(benchmark_df),
        risk_free_return_points=points_from_df(risk_free_df) if risk_free_df is not None else None,
        cumulative_risk_free_return_points=build_cumulative_return_points(risk_free_df),
        active_return_points=build_active_return_points(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
        ),
        cumulative_active_return_points=build_cumulative_active_return_points(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
        ),
    )


def _build_returns_series_diagnostics(
    *,
    request: ReturnsSeriesRequest,
    resolved_window: ResolvedWindow,
    portfolio_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    risk_free_df: pd.DataFrame | None,
) -> _ReturnsSeriesDiagnosticsResult:
    requested_points = date_range_count(
        resolved_window, frequency=request.frequency, calendar_policy=request.data_policy.calendar_policy
    )
    returned_points = len(portfolio_df)
    missing_points = max(requested_points - returned_points, 0)
    if request.data_policy.missing_data_policy == MissingDataPolicy.FAIL_FAST and missing_points > 0:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=insufficient_data_detail(f"Missing {missing_points} required points under FAIL_FAST policy."),
        )

    warnings: list[str] = []
    if request.data_policy.calendar_policy == CalendarPolicy.MARKET:
        warnings.append("MARKET calendar policy currently uses business-day approximation.")

    gaps = [
        *detect_gaps(
            portfolio_df,
            frequency=request.frequency,
            series_type="portfolio",
            calendar_policy=request.data_policy.calendar_policy,
        ),
        *(
            detect_gaps(
                benchmark_df,
                frequency=request.frequency,
                series_type="benchmark",
                calendar_policy=request.data_policy.calendar_policy,
            )
            if benchmark_df is not None
            else []
        ),
        *(
            detect_gaps(
                risk_free_df,
                frequency=request.frequency,
                series_type="risk_free",
                calendar_policy=request.data_policy.calendar_policy,
            )
            if risk_free_df is not None
            else []
        ),
    ]
    return _ReturnsSeriesDiagnosticsResult(
        requested_points=requested_points,
        returned_points=returned_points,
        diagnostics=ReturnsDiagnostics(
            coverage=SeriesCoverage(
                requested_points=requested_points,
                returned_points=returned_points,
                missing_points=missing_points,
                coverage_ratio=Decimal(str(round(returned_points / requested_points, 8)))
                if requested_points
                else Decimal("1"),
            ),
            gaps=gaps,
            policy_applied=request.data_policy,
            warnings=warnings,
        ),
    )


def _update_resolved_stateful_returns_identity(
    *,
    request: ReturnsSeriesRequest,
    resolved_window: ResolvedWindow,
    point_outputs: _ReturnsSeriesPointOutputs,
    resolved_benchmark_id: str | None,
    resolved_benchmark_return_source: BenchmarkReturnSource,
) -> _ReturnsSeriesIdentity:
    resolved_stateful_payload = _build_stateful_resolved_returns_payload(
        request=request,
        resolved_window=resolved_window,
        portfolio_records=_records_from_points(point_outputs.portfolio_return_points) or [],
        benchmark_records=_records_from_points(point_outputs.benchmark_return_points),
        risk_free_records=_records_from_points(point_outputs.risk_free_return_points),
        resolved_benchmark_id=resolved_benchmark_id,
        resolved_benchmark_return_source=resolved_benchmark_return_source.value if resolved_benchmark_id else None,
    )
    input_fingerprint, calculation_hash = generate_canonical_hash(
        resolved_stateful_payload,
        "returns-series-v1",
    )
    execution_registry.update_execution_identity(
        request.calculation_id,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    return _ReturnsSeriesIdentity(
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )


def _build_returns_series_response(
    *,
    request: ReturnsSeriesRequest,
    resolved_window: ResolvedWindow,
    point_outputs: _ReturnsSeriesPointOutputs,
    diagnostics_result: _ReturnsSeriesDiagnosticsResult,
    effective_input_mode: InputMode,
    input_fingerprint: str,
    calculation_hash: str,
    resolved_benchmark_id: str | None,
    resolved_benchmark_return_source: BenchmarkReturnSource | None,
) -> ReturnsSeriesResponse:
    return ReturnsSeriesResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        as_of_date=request.as_of_date,
        frequency=request.frequency,
        metric_basis=request.metric_basis,
        resolved_window=resolved_window,
        benchmark_context=(
            ReturnsSeriesBenchmarkContext(
                benchmark_id=resolved_benchmark_id,
                return_source=resolved_benchmark_return_source,
            )
            if resolved_benchmark_id is not None and resolved_benchmark_return_source is not None
            else None
        ),
        series=ReturnsSeriesPayload(
            portfolio_returns=point_outputs.portfolio_return_points,
            cumulative_portfolio_returns=point_outputs.cumulative_portfolio_return_points,
            benchmark_returns=point_outputs.benchmark_return_points,
            cumulative_benchmark_returns=point_outputs.cumulative_benchmark_return_points,
            risk_free_returns=point_outputs.risk_free_return_points,
            cumulative_risk_free_returns=point_outputs.cumulative_risk_free_return_points,
            active_returns=point_outputs.active_return_points,
            cumulative_active_returns=point_outputs.cumulative_active_return_points,
        ),
        provenance=ReturnsProvenance(
            input_mode=effective_input_mode,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        ),
        diagnostics=diagnostics_result.diagnostics,
        metadata=ReturnsMetadata(
            generated_at=datetime.now(UTC),
            correlation_id=correlation_id_var.get() or None,
            request_id=request_id_var.get() or None,
            trace_id=trace_id_var.get() or None,
        ),
    )


async def calculate_returns_series(
    request: ReturnsSeriesRequest,
    *,
    source_input_mode: InputMode | None = None,
    resolved_benchmark_id_override: str | None = None,
    resolved_benchmark_return_source_override: str | None = None,
) -> ReturnsSeriesResponse:
    return await _calculate_returns_series(
        request,
        source_input_mode=source_input_mode,
        resolved_benchmark_id_override=resolved_benchmark_id_override,
        resolved_benchmark_return_source_override=resolved_benchmark_return_source_override,
    )


async def _resolve_returns_series_execution_context(
    *,
    request: ReturnsSeriesRequest,
    source_input_mode: InputMode | None,
    resolved_benchmark_id_override: str | None,
    resolved_benchmark_return_source_override: str | None,
) -> _ReturnsSeriesExecutionContext:
    input_fingerprint, calculation_hash = generate_canonical_hash(request, "returns-series-v1")
    effective_input_mode = source_input_mode or request.input_mode
    resolved_window = resolve_window(request)
    resolved_benchmark_id: str | None = resolved_benchmark_id_override or (
        request.benchmark.benchmark_id if request.benchmark else None
    )
    resolved_benchmark_return_source = (
        BenchmarkReturnSource(resolved_benchmark_return_source_override)
        if resolved_benchmark_return_source_override is not None
        else _get_requested_benchmark_return_source(request)
    )

    if request.input_mode == InputMode.STATEFUL:
        resolved_stateful_request = await resolve_stateful_returns_series_request(request)
        request = resolved_stateful_request.request
        resolved_benchmark_id = resolved_stateful_request.resolved_benchmark_id
        if resolved_stateful_request.resolved_benchmark_return_source is not None:
            resolved_benchmark_return_source = BenchmarkReturnSource(
                resolved_stateful_request.resolved_benchmark_return_source
            )
        input_fingerprint, calculation_hash = generate_canonical_hash(
            resolved_stateful_request.identity_payload,
            "returns-series-v1",
        )
        execution_registry.update_execution_identity(
            request.calculation_id,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
        resolved_window = resolve_window(request)

    return _ReturnsSeriesExecutionContext(
        request=request,
        resolved_window=resolved_window,
        effective_input_mode=effective_input_mode,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        resolved_benchmark_id=resolved_benchmark_id,
        resolved_benchmark_return_source=resolved_benchmark_return_source,
    )


async def _calculate_returns_series(
    request: ReturnsSeriesRequest,
    *,
    source_input_mode: InputMode | None = None,
    resolved_benchmark_id_override: str | None = None,
    resolved_benchmark_return_source_override: str | None = None,
) -> ReturnsSeriesResponse:
    execution_registry.mark_running(request.calculation_id)
    active_stage: str | None = None
    try:
        context = await _resolve_returns_series_execution_context(
            request=request,
            source_input_mode=source_input_mode,
            resolved_benchmark_id_override=resolved_benchmark_id_override,
            resolved_benchmark_return_source_override=resolved_benchmark_return_source_override,
        )
        request = context.request

        portfolio_df, benchmark_df, risk_free_df = _prepare_stateless_returns_series_dataframes(
            request=request,
            resolved_window=context.resolved_window,
        )

        active_stage = EXECUTION_STAGE_EXECUTION
        execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_EXECUTION)
        portfolio_df, benchmark_df, risk_free_df = _apply_strict_intersection_policy(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
            risk_free_df=risk_free_df,
            missing_data_policy=request.data_policy.missing_data_policy,
        )
        portfolio_df, benchmark_df, risk_free_df = _apply_selected_fill_method(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
            risk_free_df=risk_free_df,
            fill_method=request.data_policy.fill_method,
        )

        point_outputs = _build_returns_series_point_outputs(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
            risk_free_df=risk_free_df,
        )

        input_fingerprint = context.input_fingerprint
        calculation_hash = context.calculation_hash
        if context.effective_input_mode == InputMode.STATEFUL:
            resolved_identity = _update_resolved_stateful_returns_identity(
                request=request,
                resolved_window=context.resolved_window,
                point_outputs=point_outputs,
                resolved_benchmark_id=context.resolved_benchmark_id,
                resolved_benchmark_return_source=context.resolved_benchmark_return_source,
            )
            input_fingerprint = resolved_identity.input_fingerprint
            calculation_hash = resolved_identity.calculation_hash

        diagnostics_result = _build_returns_series_diagnostics(
            request=request,
            resolved_window=context.resolved_window,
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
            risk_free_df=risk_free_df,
        )

        response = _build_returns_series_response(
            request=request,
            resolved_window=context.resolved_window,
            point_outputs=point_outputs,
            diagnostics_result=diagnostics_result,
            effective_input_mode=context.effective_input_mode,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            resolved_benchmark_id=context.resolved_benchmark_id,
            resolved_benchmark_return_source=context.resolved_benchmark_return_source,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_EXECUTION,
            details={
                "requested_points": diagnostics_result.requested_points,
                "returned_points": diagnostics_result.returned_points,
            },
        )
        execution_registry.mark_complete(request.calculation_id)
        return response
    except HTTPException as exc:
        message = exc.detail["message"] if isinstance(exc.detail, dict) and "message" in exc.detail else str(exc.detail)
        fail_execution(calculation_id=request.calculation_id, message=message, active_stage=active_stage)
        raise
    except Exception as exc:
        fail_execution(
            calculation_id=request.calculation_id,
            message=f"Unexpected returns-series failure: {exc}",
            active_stage=active_stage,
        )
        raise


async def resolve_stateful_returns_series_request(
    request: ReturnsSeriesRequest,
) -> ResolvedStatefulReturnsSeriesRequest:
    if request.input_mode != InputMode.STATEFUL:
        raise ValueError("resolve_stateful_returns_series_request only supports stateful requests")

    active_settings = get_settings()
    resolved_window = resolve_window(request)
    stateful_input = request.stateful_input
    if stateful_input is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=invalid_request_detail("stateful_input is required in stateful mode."),
        )

    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_RETRIEVAL)
    stateful_input_service = build_stateful_input_service(settings=active_settings)
    portfolio_source = await _retrieve_stateful_returns_series_portfolio_source(
        active_settings=active_settings,
        stateful_input_service=stateful_input_service,
        request=request,
        resolved_window=resolved_window,
    )

    observations = portfolio_source.observations
    resolved_benchmark_id: str | None = request.benchmark.benchmark_id if request.benchmark else None
    resolved_benchmark_return_source = _get_requested_benchmark_return_source(request)
    benchmark_resolution = await _resolve_stateful_returns_series_benchmark_source(
        request=request,
        stateful_input_service=stateful_input_service,
        resolved_window=resolved_window,
        resolved_benchmark_id=resolved_benchmark_id,
        resolved_benchmark_return_source=resolved_benchmark_return_source,
    )
    resolved_benchmark_id = benchmark_resolution.benchmark_id

    risk_free_points, risk_free_payload = await _retrieve_stateful_returns_series_risk_free(
        request=request,
        stateful_input_service=stateful_input_service,
        resolved_window=resolved_window,
    )

    execution_registry.complete_stage(
        request.calculation_id,
        EXECUTION_STAGE_RETRIEVAL,
        details=_stateful_returns_retrieval_stage_details(
            observations=observations,
            portfolio_source=portfolio_source,
            benchmark_resolution=benchmark_resolution,
            risk_free_points=risk_free_points,
            risk_free_payload=risk_free_payload,
        ),
    )

    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION)
    resolved_stateful_request = _build_resolved_stateful_returns_series_request(
        request=request,
        resolved_window=resolved_window,
        observations=observations,
        portfolio_performance_start_date=portfolio_source.performance_start_date,
        benchmark_resolution=benchmark_resolution,
        risk_free_points=risk_free_points,
        resolved_benchmark_id=resolved_benchmark_id,
        resolved_benchmark_return_source=resolved_benchmark_return_source,
    )
    input_count = len(observations) + benchmark_resolution.benchmark_work_units + len(risk_free_points or [])
    return ResolvedStatefulReturnsSeriesRequest(
        request=resolved_stateful_request.request,
        identity_payload=resolved_stateful_request.identity_payload,
        input_count=input_count,
        resolved_benchmark_id=resolved_benchmark_id,
        resolved_benchmark_return_source=(resolved_benchmark_return_source.value if resolved_benchmark_id else None),
        benchmark_work_units=benchmark_resolution.benchmark_work_units,
    )


async def _retrieve_stateful_returns_series_portfolio_source(
    *,
    active_settings: Any,
    stateful_input_service: Any,
    request: ReturnsSeriesRequest,
    resolved_window: ResolvedWindow,
) -> StatefulPortfolioInput:
    try:
        return await retrieve_stateful_portfolio_input(
            settings=active_settings,
            stateful_input_service=stateful_input_service,
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.as_of_date,
            start_date=resolved_window.start_date,
            end_date=resolved_window.end_date,
            reporting_currency=request.reporting_currency,
            consumer_system=LOTUS_PERFORMANCE_CONSUMER_SYSTEM,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=source_unavailable_detail(str(exc.detail)),
            ) from exc
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=insufficient_data_detail(str(exc.detail)),
        ) from exc
