from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Iterable

import pandas as pd
from fastapi import APIRouter, HTTPException, status

from adapters.api_adapter import create_engine_config, create_engine_dataframe
from app.core.config import get_settings
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
    ReturnsSeriesPayload,
    ReturnsSeriesRequest,
    ReturnsSeriesResponse,
    SeriesCoverage,
    SeriesGap,
)
from app.observability import correlation_id_var, request_id_var, trace_id_var
from app.services.core_integration_service import CoreIntegrationService
from common.enums import Frequency, PeriodType
from core.repro import generate_canonical_hash
from engine.compute import run_calculations
from engine.schema import PortfolioColumns

router = APIRouter(tags=["Integration"])
settings = get_settings()


def _period_start(as_of_date: date, period: ReturnsRelativePeriod, year: int | None) -> date:
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


def _resolve_window(request: ReturnsSeriesRequest) -> ResolvedWindow:
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
    start_date = _period_start(request.as_of_date, request.window.period, request.window.year)
    return ResolvedWindow(
        start_date=start_date,
        end_date=request.as_of_date,
        resolved_period_label=request.window.period.value,
    )


def _to_dataframe(points: Iterable[ReturnPoint], *, series_type: str) -> pd.DataFrame:
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
    df = df.sort_values("date")
    return df


def _filter_window(df: pd.DataFrame, *, resolved_window: ResolvedWindow) -> pd.DataFrame:
    mask = (df["date"].dt.date >= resolved_window.start_date) & (df["date"].dt.date <= resolved_window.end_date)
    window_df = df[mask].copy()
    if window_df.empty:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INSUFFICIENT_DATA", "message": "No observations in resolved window."},
        )
    return window_df


def _resample_returns(df: pd.DataFrame, *, frequency: ReturnsFrequency) -> pd.DataFrame:
    if frequency == ReturnsFrequency.DAILY:
        return df
    indexed = df.set_index("date")
    if frequency == ReturnsFrequency.WEEKLY:
        grouped = indexed["return_value"].resample("W-FRI").apply(lambda x: (1 + x).prod() - 1)
    else:
        grouped = indexed["return_value"].resample("ME").apply(lambda x: (1 + x).prod() - 1)
    out = grouped.dropna().reset_index()
    return out


def _date_range_count(
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


def _detect_gaps(df: pd.DataFrame, *, frequency: ReturnsFrequency, series_type: str) -> list[SeriesGap]:
    if len(df) < 2:
        return []
    expected_days = 1 if frequency == ReturnsFrequency.DAILY else (7 if frequency == ReturnsFrequency.WEEKLY else 31)
    gaps: list[SeriesGap] = []
    dates = list(df["date"].dt.date)
    for prev, curr in zip(dates, dates[1:]):
        delta = (curr - prev).days
        if delta > expected_days + 1:
            gaps.append(
                SeriesGap(
                    series_type=series_type,
                    from_date=prev,
                    to_date=curr,
                    gap_days=delta - 1,
                )
            )
    return gaps


def _points_from_df(df: pd.DataFrame) -> list[ReturnPoint]:
    out: list[ReturnPoint] = []
    for _, row in df.iterrows():
        value = Decimal(str(row["return_value"])).quantize(Decimal("0.000000000001"))
        out.append(
            ReturnPoint(
                date=row["date"].date(),
                return_value=value,
            )
        )
    return out


def _core_frequency_label(_frequency: ReturnsFrequency) -> str:
    # lotus-performance owns aggregation semantics; consume daily from lotus-core.
    return "daily"


def _core_points_to_dataframe(
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
                ReturnPoint(
                    date=date.fromisoformat(date_raw),
                    return_value=Decimal(str(value_raw)),
                )
            )
        except (ValueError, ArithmeticError):
            continue
    return _to_dataframe(normalized_points, series_type=series_type)


def _portfolio_timeseries_to_valuation_points(*, observations: list[dict[str, object]]) -> list[dict[str, object]]:
    valuation_points: list[dict[str, object]] = []
    for point in observations:
        valuation_date = point.get("valuation_date")
        begin_mv = point.get("beginning_market_value")
        end_mv = point.get("ending_market_value")
        cash_flows_raw = point.get("cash_flows", [])
        if not isinstance(valuation_date, str) or begin_mv is None or end_mv is None:
            continue
        bod_cf = Decimal("0")
        eod_cf = Decimal("0")
        if isinstance(cash_flows_raw, list):
            for flow in cash_flows_raw:
                if not isinstance(flow, dict):
                    continue
                amount = flow.get("amount")
                timing = flow.get("timing")
                if amount is None or timing not in {"bod", "eod"}:
                    continue
                dec_amount = Decimal(str(amount))
                if timing == "bod":
                    bod_cf += dec_amount
                else:
                    eod_cf += dec_amount
        valuation_points.append(
            {
                "day": 0,
                "perf_date": valuation_date,
                "begin_mv": Decimal(str(begin_mv)),
                "end_mv": Decimal(str(end_mv)),
                "bod_cf": bod_cf,
                "eod_cf": eod_cf,
            }
        )
    if not valuation_points:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INSUFFICIENT_DATA",
                "message": "No valid valuation observations after canonical normalization.",
            },
        )
    return valuation_points


def _daily_ror_from_portfolio_timeseries(
    *,
    observations: list[dict[str, object]],
    performance_start_date: date,
    resolved_window: ResolvedWindow,
    metric_basis: str,
) -> pd.DataFrame:
    valuation_points = _portfolio_timeseries_to_valuation_points(observations=observations)
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
            # returns-series contract uses decimal form (0.0012 = 12bps).
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


@router.post(
    "/returns/series",
    response_model=ReturnsSeriesResponse,
    summary="Get canonical return series for downstream analytics",
    description=(
        "Returns canonical portfolio/benchmark/risk-free return time series for stateful analytics consumers. "
        "Supports stateless (request-supplied inputs) and stateful (platform-sourced inputs) modes."
    ),
)
async def get_returns_series(request: ReturnsSeriesRequest) -> ReturnsSeriesResponse:
    resolved_window = _resolve_window(request)
    benchmark_df = None
    risk_free_df = None
    if request.input_mode == InputMode.STATEFUL:
        core_service = CoreIntegrationService(
            base_url=settings.CORE_QUERY_BASE_URL,
            timeout_seconds=settings.CORE_TIMEOUT_SECONDS,
            max_retries=settings.CORE_MAX_RETRIES,
            retry_backoff_seconds=settings.CORE_RETRY_BACKOFF_SECONDS,
        )
        stateful_input = request.stateful_input
        if stateful_input is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "stateful_input is required in stateful mode."},
            )
        upstream_status, upstream_payload = await core_service.get_portfolio_analytics_timeseries(
            portfolio_id=request.portfolio_id,
            as_of_date=request.as_of_date,
            start_date=resolved_window.start_date,
            end_date=resolved_window.end_date,
            reporting_currency=request.reporting_currency,
            consumer_system=stateful_input.consumer_system,
        )
        if upstream_status >= status.HTTP_400_BAD_REQUEST:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "SOURCE_UNAVAILABLE",
                    "message": f"stateful portfolio timeseries source unavailable ({upstream_status}).",
                },
            )
        observations = upstream_payload.get("observations")
        if not isinstance(observations, list) or not observations:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "INSUFFICIENT_DATA", "message": "Stateful source returned no observations."},
            )
        open_date_raw = upstream_payload.get("portfolio_open_date")
        if not isinstance(open_date_raw, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "INSUFFICIENT_DATA", "message": "Stateful source missing portfolio_open_date."},
            )
        try:
            performance_start_date = date.fromisoformat(open_date_raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "INSUFFICIENT_DATA", "message": "Invalid portfolio_open_date from stateful source."},
            ) from exc
        portfolio_df = _resample_returns(
            _daily_ror_from_portfolio_timeseries(
                observations=observations,
                performance_start_date=performance_start_date,
                resolved_window=resolved_window,
                metric_basis=request.metric_basis.value,
            ),
            frequency=request.frequency,
        )

        benchmark_id = request.benchmark.benchmark_id if request.benchmark else None
        if request.series_selection.include_benchmark and not benchmark_id:
            assignment_status, assignment_payload = await core_service.get_benchmark_assignment(
                portfolio_id=request.portfolio_id,
                as_of_date=request.as_of_date,
                reporting_currency=request.reporting_currency,
            )
            if assignment_status == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "RESOURCE_NOT_FOUND", "message": "No benchmark assignment found for portfolio."},
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
        if request.series_selection.include_benchmark and benchmark_id:
            benchmark_status, benchmark_payload = await core_service.get_benchmark_return_series(
                benchmark_id=benchmark_id,
                as_of_date=request.as_of_date,
                start_date=resolved_window.start_date,
                end_date=resolved_window.end_date,
                frequency=_core_frequency_label(request.frequency),
            )
            if benchmark_status == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "RESOURCE_NOT_FOUND", "message": f"No benchmark return series for {benchmark_id}."},
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
            benchmark_df = _resample_returns(
                _filter_window(
                    _core_points_to_dataframe(
                        points=benchmark_points,
                        date_key="series_date",
                        value_key="benchmark_return",
                        series_type="benchmark",
                    ),
                    resolved_window=resolved_window,
                ),
                frequency=request.frequency,
            )
        if request.series_selection.include_risk_free:
            if not request.reporting_currency:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "INVALID_REQUEST",
                        "message": "reporting_currency is required for risk-free series in stateful mode.",
                    },
                )
            risk_free_status, risk_free_payload = await core_service.get_risk_free_series(
                currency=request.reporting_currency,
                as_of_date=request.as_of_date,
                start_date=resolved_window.start_date,
                end_date=resolved_window.end_date,
                frequency=_core_frequency_label(request.frequency),
                series_mode="return_series",
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
            risk_free_df = _resample_returns(
                _filter_window(
                    _core_points_to_dataframe(
                        points=risk_free_points,
                        date_key="series_date",
                        value_key="value",
                        series_type="risk_free",
                    ),
                    resolved_window=resolved_window,
                ),
                frequency=request.frequency,
            )
    else:
        stateless_input = request.stateless_input
        if stateless_input is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "stateless_input is required in stateless mode.",
                },
            )

        portfolio_df = _resample_returns(
            _filter_window(
                _to_dataframe(stateless_input.portfolio_returns, series_type="portfolio"),
                resolved_window=resolved_window,
            ),
            frequency=request.frequency,
        )

        if request.series_selection.include_benchmark:
            benchmark_df = _resample_returns(
                _filter_window(
                    _to_dataframe(stateless_input.benchmark_returns or [], series_type="benchmark"),
                    resolved_window=resolved_window,
                ),
                frequency=request.frequency,
            )
        if request.series_selection.include_risk_free:
            risk_free_df = _resample_returns(
                _filter_window(
                    _to_dataframe(stateless_input.risk_free_returns or [], series_type="risk_free"),
                    resolved_window=resolved_window,
                ),
                frequency=request.frequency,
            )

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

    requested_points = _date_range_count(
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

    input_fingerprint, calculation_hash = generate_canonical_hash(request, "returns-series-v1")
    diagnostics = ReturnsDiagnostics(
        coverage=SeriesCoverage(
            requested_points=requested_points,
            returned_points=returned_points,
            missing_points=missing_points,
            coverage_ratio=Decimal(str(round(returned_points / requested_points, 8)))
            if requested_points
            else Decimal("1"),
        ),
        gaps=[
            *_detect_gaps(portfolio_df, frequency=request.frequency, series_type="portfolio"),
            *(
                _detect_gaps(benchmark_df, frequency=request.frequency, series_type="benchmark")
                if benchmark_df is not None
                else []
            ),
            *(
                _detect_gaps(risk_free_df, frequency=request.frequency, series_type="risk_free")
                if risk_free_df is not None
                else []
            ),
        ],
        policy_applied=request.data_policy,
        warnings=warnings,
    )

    return ReturnsSeriesResponse(
        portfolio_id=request.portfolio_id,
        as_of_date=request.as_of_date,
        frequency=request.frequency,
        metric_basis=request.metric_basis,
        resolved_window=resolved_window,
        series=ReturnsSeriesPayload(
            portfolio_returns=_points_from_df(portfolio_df),
            benchmark_returns=_points_from_df(benchmark_df) if benchmark_df is not None else None,
            risk_free_returns=_points_from_df(risk_free_df) if risk_free_df is not None else None,
        ),
        provenance=ReturnsProvenance(
            input_mode=request.input_mode,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        ),
        diagnostics=diagnostics,
        metadata=ReturnsMetadata(
            generated_at=datetime.now(UTC),
            correlation_id=correlation_id_var.get() or None,
            request_id=request_id_var.get() or None,
            trace_id=trace_id_var.get() or None,
        ),
    )
