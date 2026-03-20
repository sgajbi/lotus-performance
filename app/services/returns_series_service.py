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
from app.services.execution_registry import execution_registry
from app.services.portfolio_source_service import (
    build_stateful_input_service,
)
from app.services.stateful_benchmark_input_service import build_stateful_benchmark_input
from app.services.stateful_performance_input_service import retrieve_stateful_portfolio_input
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points
from common.enums import Frequency, PeriodType
from core.repro import generate_canonical_hash
from engine.benchmarks import benchmark_return_points_to_dataframe, calculate_benchmark_returns
from engine.compute import run_calculations
from engine.schema import PortfolioColumns

DEFAULT_STATEFUL_CONSUMER_SYSTEM = "lotus-performance"
RETURN_POINT_QUANTUM = Decimal("0.000000000001")


@dataclass(frozen=True)
class ResolvedStatefulReturnsSeriesRequest:
    request: ReturnsSeriesRequest
    identity_payload: dict[str, Any]
    input_count: int
    resolved_benchmark_id: str | None
    resolved_benchmark_return_source: str | None
    benchmark_work_units: int


def period_start(as_of_date: date, period: ReturnsRelativePeriod, year: int | None) -> date:
    as_of = pd.Timestamp(as_of_date)
    if period == ReturnsRelativePeriod.MTD:
        return as_of.to_period("M").start_time.date()
    if period == ReturnsRelativePeriod.QTD:
        return as_of.to_period("Q").start_time.date()
    if period == ReturnsRelativePeriod.YTD:
        return as_of.to_period("Y").start_time.date()
    if period == ReturnsRelativePeriod.ONE_YEAR:
        return (as_of - pd.DateOffset(years=1) + pd.Timedelta(days=1)).date()
    if period == ReturnsRelativePeriod.THREE_YEAR:
        return (as_of - pd.DateOffset(years=3) + pd.Timedelta(days=1)).date()
    if period == ReturnsRelativePeriod.FIVE_YEAR:
        return (as_of - pd.DateOffset(years=5) + pd.Timedelta(days=1)).date()
    if period == ReturnsRelativePeriod.SI:
        return date(1900, 1, 1)
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
            detail={"code": "INVALID_REQUEST", "message": "window.period is required when mode=RELATIVE"},
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INSUFFICIENT_DATA", "message": f"{series_type} series is empty."},
        )
    if df["date"].duplicated().any():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": f"{series_type} series contains duplicate dates."},
        )
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


def filter_window(df: pd.DataFrame, *, resolved_window: ResolvedWindow) -> pd.DataFrame:
    mask = (df["date"].dt.date >= resolved_window.start_date) & (df["date"].dt.date <= resolved_window.end_date)
    window_df = df[mask].copy()
    if window_df.empty:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INSUFFICIENT_DATA", "message": "No observations in resolved window."},
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


def detect_gaps(df: pd.DataFrame, *, frequency: ReturnsFrequency, series_type: str) -> list[SeriesGap]:
    if len(df) < 2:
        return []
    expected_days = 1 if frequency == ReturnsFrequency.DAILY else (7 if frequency == ReturnsFrequency.WEEKLY else 31)
    gaps: list[SeriesGap] = []
    dates = list(df["date"].dt.date)
    for prev, curr in zip(dates, dates[1:]):
        delta = (curr - prev).days
        if delta > expected_days + 1:
            gaps.append(SeriesGap(series_type=series_type, from_date=prev, to_date=curr, gap_days=delta - 1))
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INSUFFICIENT_DATA", "message": "No portfolio return observations in resolved window."},
        )
    output_df = pd.DataFrame(
        {
            "date": pd.to_datetime(daily_results_df[PortfolioColumns.PERF_DATE.value]),
            "return_value": [
                (Decimal(str(value)) / Decimal("100") if not pd.isna(pd.to_numeric(value, errors="coerce")) else None)
                for value in daily_results_df[PortfolioColumns.DAILY_ROR.value]
            ],
        }
    )
    output_df = output_df.dropna(subset=["return_value"]).sort_values("date")
    if output_df.empty:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INSUFFICIENT_DATA",
                "message": "No valid portfolio return observations after normalization.",
            },
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INSUFFICIENT_DATA", "message": "Benchmark series is empty."},
        )
    benchmark_df = daily_returns_df[["date", "benchmark_return"]].copy()
    benchmark_df["date"] = pd.to_datetime(benchmark_df["date"])
    benchmark_df = benchmark_df.rename(columns={"benchmark_return": "return_value"}).sort_values("date")
    if benchmark_df["date"].duplicated().any():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "benchmark series contains duplicate dates."},
        )
    return benchmark_df


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


async def _calculate_returns_series(
    request: ReturnsSeriesRequest,
    *,
    source_input_mode: InputMode | None = None,
    resolved_benchmark_id_override: str | None = None,
    resolved_benchmark_return_source_override: str | None = None,
) -> ReturnsSeriesResponse:
    input_fingerprint, calculation_hash = generate_canonical_hash(request, "returns-series-v1")
    effective_input_mode = source_input_mode or request.input_mode
    execution_registry.mark_running(request.calculation_id)
    active_stage: str | None = None
    try:
        resolved_window = resolve_window(request)
        benchmark_df = None
        risk_free_df = None
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
            resolved_benchmark_return_source = (
                BenchmarkReturnSource(resolved_stateful_request.resolved_benchmark_return_source)
                if resolved_stateful_request.resolved_benchmark_return_source is not None
                else None
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

        stateless_input = request.stateless_input
        if stateless_input is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "stateless_input is required in stateless mode."},
            )
        portfolio_df = resample_returns(
            filter_window(
                to_dataframe(stateless_input.portfolio_returns, series_type="portfolio"),
                resolved_window=resolved_window,
            ),
            frequency=request.frequency,
        )
        if request.series_selection.include_benchmark:
            benchmark_df = resample_returns(
                filter_window(
                    to_dataframe(stateless_input.benchmark_returns or [], series_type="benchmark"),
                    resolved_window=resolved_window,
                ),
                frequency=request.frequency,
            )
        if request.series_selection.include_risk_free:
            risk_free_df = resample_returns(
                filter_window(
                    to_dataframe(stateless_input.risk_free_returns or [], series_type="risk_free"),
                    resolved_window=resolved_window,
                ),
                frequency=request.frequency,
            )

        active_stage = "execution"
        execution_registry.start_stage(request.calculation_id, "execution")
        if request.data_policy.missing_data_policy == MissingDataPolicy.STRICT_INTERSECTION:
            common_dates = set(portfolio_df["date"])
            if benchmark_df is not None:
                common_dates &= set(benchmark_df["date"])
            if risk_free_df is not None:
                common_dates &= set(risk_free_df["date"])
            if not common_dates:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "INSUFFICIENT_DATA", "message": "No overlapping dates across selected series."},
                )
            portfolio_df = portfolio_df[portfolio_df["date"].isin(common_dates)].sort_values("date")
            if benchmark_df is not None:
                benchmark_df = benchmark_df[benchmark_df["date"].isin(common_dates)].sort_values("date")
            if risk_free_df is not None:
                risk_free_df = risk_free_df[risk_free_df["date"].isin(common_dates)].sort_values("date")

        if request.data_policy.fill_method == FillMethod.FORWARD_FILL:
            if benchmark_df is not None:
                benchmark_df = benchmark_df.set_index("date").reindex(portfolio_df["date"]).ffill().reset_index()
            if risk_free_df is not None:
                risk_free_df = risk_free_df.set_index("date").reindex(portfolio_df["date"]).ffill().reset_index()
        elif request.data_policy.fill_method == FillMethod.ZERO_FILL:
            if benchmark_df is not None:
                benchmark_df = benchmark_df.set_index("date").reindex(portfolio_df["date"]).fillna(0.0).reset_index()
            if risk_free_df is not None:
                risk_free_df = risk_free_df.set_index("date").reindex(portfolio_df["date"]).fillna(0.0).reset_index()

        portfolio_return_points = points_from_df(portfolio_df)
        cumulative_portfolio_return_points = build_cumulative_return_points(portfolio_df)
        benchmark_return_points = points_from_df(benchmark_df) if benchmark_df is not None else None
        cumulative_benchmark_return_points = build_cumulative_return_points(benchmark_df)
        risk_free_return_points = points_from_df(risk_free_df) if risk_free_df is not None else None
        cumulative_risk_free_return_points = build_cumulative_return_points(risk_free_df)
        active_return_points = build_active_return_points(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
        )
        cumulative_active_return_points = build_cumulative_active_return_points(
            portfolio_df=portfolio_df,
            benchmark_df=benchmark_df,
        )

        if effective_input_mode == InputMode.STATEFUL:
            resolved_stateful_payload = _build_stateful_resolved_returns_payload(
                request=request,
                resolved_window=resolved_window,
                portfolio_records=_records_from_points(portfolio_return_points) or [],
                benchmark_records=_records_from_points(benchmark_return_points),
                risk_free_records=_records_from_points(risk_free_return_points),
                resolved_benchmark_id=resolved_benchmark_id,
                resolved_benchmark_return_source=(
                    resolved_benchmark_return_source.value if resolved_benchmark_id else None
                ),
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

        requested_points = date_range_count(
            resolved_window, frequency=request.frequency, calendar_policy=request.data_policy.calendar_policy
        )
        returned_points = len(portfolio_df)
        missing_points = max(requested_points - returned_points, 0)
        if request.data_policy.missing_data_policy == MissingDataPolicy.FAIL_FAST and missing_points > 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INSUFFICIENT_DATA",
                    "message": f"Missing {missing_points} required points under FAIL_FAST policy.",
                },
            )

        warnings: list[str] = []
        if request.data_policy.calendar_policy == CalendarPolicy.MARKET:
            warnings.append("MARKET calendar policy currently uses business-day approximation.")

        response = ReturnsSeriesResponse(
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
                portfolio_returns=portfolio_return_points,
                cumulative_portfolio_returns=cumulative_portfolio_return_points,
                benchmark_returns=benchmark_return_points,
                cumulative_benchmark_returns=cumulative_benchmark_return_points,
                risk_free_returns=risk_free_return_points,
                cumulative_risk_free_returns=cumulative_risk_free_return_points,
                active_returns=active_return_points,
                cumulative_active_returns=cumulative_active_return_points,
            ),
            provenance=ReturnsProvenance(
                input_mode=effective_input_mode,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            ),
            diagnostics=ReturnsDiagnostics(
                coverage=SeriesCoverage(
                    requested_points=requested_points,
                    returned_points=returned_points,
                    missing_points=missing_points,
                    coverage_ratio=Decimal(str(round(returned_points / requested_points, 8)))
                    if requested_points
                    else Decimal("1"),
                ),
                gaps=[
                    *detect_gaps(portfolio_df, frequency=request.frequency, series_type="portfolio"),
                    *(
                        detect_gaps(benchmark_df, frequency=request.frequency, series_type="benchmark")
                        if benchmark_df is not None
                        else []
                    ),
                    *(
                        detect_gaps(risk_free_df, frequency=request.frequency, series_type="risk_free")
                        if risk_free_df is not None
                        else []
                    ),
                ],
                policy_applied=request.data_policy,
                warnings=warnings,
            ),
            metadata=ReturnsMetadata(
                generated_at=datetime.now(UTC),
                correlation_id=correlation_id_var.get() or None,
                request_id=request_id_var.get() or None,
                trace_id=trace_id_var.get() or None,
            ),
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "execution",
            details={"requested_points": requested_points, "returned_points": returned_points},
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
            detail={"code": "INVALID_REQUEST", "message": "stateful_input is required in stateful mode."},
        )

    execution_registry.start_stage(request.calculation_id, "retrieval")
    stateful_input_service = build_stateful_input_service(settings=active_settings)
    try:
        portfolio_source = await retrieve_stateful_portfolio_input(
            settings=active_settings,
            stateful_input_service=stateful_input_service,
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.as_of_date,
            start_date=resolved_window.start_date,
            end_date=resolved_window.end_date,
            reporting_currency=request.reporting_currency,
            consumer_system=DEFAULT_STATEFUL_CONSUMER_SYSTEM,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "SOURCE_UNAVAILABLE",
                    "message": str(exc.detail),
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INSUFFICIENT_DATA",
                "message": str(exc.detail),
            },
        ) from exc

    observations = portfolio_source.observations
    resolved_benchmark_id: str | None = request.benchmark.benchmark_id if request.benchmark else None
    resolved_benchmark_return_source = _get_requested_benchmark_return_source(request)
    benchmark_id = resolved_benchmark_id
    if request.series_selection.include_benchmark and not benchmark_id:
        assignment_status, assignment_payload = await stateful_input_service.get_benchmark_assignment(
            portfolio_id=request.portfolio_id,
            as_of_date=request.as_of_date,
            reporting_currency=request.reporting_currency,
        )
        if assignment_status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "RESOURCE_NOT_FOUND",
                    "message": "No benchmark assignment found for portfolio.",
                },
            )
        if assignment_status >= status.HTTP_400_BAD_REQUEST:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "SOURCE_UNAVAILABLE",
                    "message": f"Benchmark assignment source unavailable ({assignment_status}).",
                },
            )
        benchmark_id_raw = assignment_payload.get("benchmark_id")
        benchmark_id = str(benchmark_id_raw) if benchmark_id_raw else None
        if not benchmark_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "CONTRACT_VIOLATION_UPSTREAM",
                    "message": "Benchmark assignment payload missing benchmark_id.",
                },
            )
        resolved_benchmark_id = benchmark_id

    benchmark_points: list[dict[str, Any]] | None = None
    benchmark_df: pd.DataFrame | None = None
    benchmark_source_details: dict[str, int] = {}
    benchmark_work_units = 0
    if request.series_selection.include_benchmark and benchmark_id:
        if resolved_benchmark_return_source == BenchmarkReturnSource.VENDOR_SERIES:
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
                    detail={
                        "code": "RESOURCE_NOT_FOUND",
                        "message": f"No benchmark return series for {benchmark_id}.",
                    },
                )
            if benchmark_status >= status.HTTP_400_BAD_REQUEST:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "SOURCE_UNAVAILABLE",
                        "message": f"Benchmark return-series source unavailable ({benchmark_status}).",
                    },
                )
            benchmark_points = benchmark_payload.get("points")
            if not isinstance(benchmark_points, list):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "CONTRACT_VIOLATION_UPSTREAM",
                        "message": "Benchmark return-series payload missing points list.",
                    },
                )
            benchmark_source_details = {
                "benchmark_points": len(benchmark_points),
                "benchmark_chunk_count": int(benchmark_payload.get("retrieval_metadata", {}).get("chunk_count", 0)),
                "benchmark_page_count": int(benchmark_payload.get("retrieval_metadata", {}).get("page_count", 0)),
            }
            benchmark_work_units = len(benchmark_points)
        else:
            normalized_benchmark_input = await build_stateful_benchmark_input(
                stateful_input_service=stateful_input_service,
                calculation_id=request.calculation_id,
                benchmark_id=benchmark_id,
                as_of_date=request.as_of_date,
                start_date=resolved_window.start_date,
                end_date=resolved_window.end_date,
                return_source=resolved_benchmark_return_source,
            )
            benchmark_df = resample_returns(
                filter_window(
                    _benchmark_daily_returns_to_dataframe(
                        calculate_benchmark_returns(
                            normalized_benchmark_input.component_observations
                        ).daily_returns_df
                        if resolved_benchmark_return_source == BenchmarkReturnSource.CALCULATED
                        else benchmark_return_points_to_dataframe(normalized_benchmark_input.benchmark_return_points)
                    ),
                    resolved_window=resolved_window,
                ),
                frequency=request.frequency,
            )
            benchmark_source_details = {
                **normalized_benchmark_input.source_details,
                "benchmark_points": len(benchmark_df),
            }
            benchmark_work_units = normalized_benchmark_input.source_details.get(
                "component_observations",
                len(benchmark_df),
            )

    risk_free_points: list[dict[str, Any]] | None = None
    risk_free_payload: dict[str, Any] | None = None
    if request.series_selection.include_risk_free:
        if not request.reporting_currency:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "reporting_currency is required for risk-free series in stateful mode.",
                },
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
                detail={
                    "code": "RESOURCE_NOT_FOUND",
                    "message": f"No risk-free series found for {request.reporting_currency}.",
                },
            )
        if risk_free_status >= status.HTTP_400_BAD_REQUEST:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "SOURCE_UNAVAILABLE",
                    "message": f"Risk-free series source unavailable ({risk_free_status}).",
                },
            )
        risk_free_points = risk_free_payload.get("points")
        if not isinstance(risk_free_points, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "CONTRACT_VIOLATION_UPSTREAM",
                    "message": "Risk-free series payload missing points list.",
                },
            )

    execution_registry.complete_stage(
        request.calculation_id,
        "retrieval",
        details={
            "portfolio_observations": len(observations),
            "benchmark_points": benchmark_source_details.get("benchmark_points", len(benchmark_points or [])),
            "benchmark_work_units": benchmark_work_units,
            "risk_free_points": len(risk_free_points or []),
            "portfolio_chunk_count": portfolio_source.retrieval_metadata.chunk_count,
            "portfolio_page_count": portfolio_source.retrieval_metadata.page_count,
            "benchmark_chunk_count": benchmark_source_details.get("benchmark_chunk_count", 0),
            "benchmark_page_count": benchmark_source_details.get("benchmark_page_count", 0),
            "risk_free_chunk_count": (
                int(risk_free_payload.get("retrieval_metadata", {}).get("chunk_count", 0))
                if risk_free_points is not None and risk_free_payload is not None
                else 0
            ),
        },
    )

    execution_registry.start_stage(request.calculation_id, "normalization")
    portfolio_df = resample_returns(
        daily_ror_from_portfolio_timeseries(
            observations=observations,
            performance_start_date=portfolio_source.performance_start_date,
            resolved_window=resolved_window,
            metric_basis=request.metric_basis.value,
        ),
        frequency=request.frequency,
    )
    if benchmark_points is not None:
        benchmark_df = resample_returns(
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
                core_points_to_dataframe(
                    points=risk_free_points,
                    date_key="series_date",
                    value_key="value",
                    series_type="risk_free",
                ),
                resolved_window=resolved_window,
            ),
            frequency=request.frequency,
        )
    execution_registry.complete_stage(
        request.calculation_id,
        "normalization",
        details={
            "portfolio_points": len(portfolio_df),
            "benchmark_points": len(benchmark_df) if benchmark_df is not None else 0,
            "risk_free_points": len(risk_free_df) if risk_free_df is not None else 0,
        },
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
        resolved_benchmark_return_source=(
            resolved_benchmark_return_source.value if resolved_benchmark_id else None
        ),
    )
    resolved_request = ReturnsSeriesRequest.model_validate(
        {
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
                "portfolio_returns": identity_payload["stateless_input"]["portfolio_returns"],
                "benchmark_returns": identity_payload["stateless_input"]["benchmark_returns"],
                "risk_free_returns": identity_payload["stateless_input"]["risk_free_returns"],
            },
        }
    )
    input_count = len(observations) + benchmark_work_units + len(risk_free_points or [])
    return ResolvedStatefulReturnsSeriesRequest(
        request=resolved_request,
        identity_payload=identity_payload,
        input_count=input_count,
        resolved_benchmark_id=resolved_benchmark_id,
        resolved_benchmark_return_source=(
            resolved_benchmark_return_source.value if resolved_benchmark_id else None
        ),
        benchmark_work_units=benchmark_work_units,
    )
