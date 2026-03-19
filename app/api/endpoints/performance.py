# app/api/endpoints/performance.py
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from adapters.api_adapter import (
    create_engine_config,
    create_engine_dataframe,
    format_breakdowns_for_response,
)
from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest, AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.attribution_responses import AttributionAcceptedResponse, AttributionResponse
from app.models.benchmark_analytics_requests import BenchmarkInputMode
from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest, MWRInputMode
from app.models.mwr_responses import MoneyWeightedReturnResponse
from app.models.performance_diagnostics import build_performance_diagnostics, build_reset_events
from app.models.responses import (
    PerformanceResponse,
    PortfolioReturnDecomposition,
    SinglePeriodPerformanceResult,
    TWRBenchmarkResponse,
)
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode, TWRResolvedExecutionRequest
from app.services.async_result_service import resolve_async_result
from app.services.attribution_mode_service import resolve_attribution_request
from app.services.attribution_service import calculate_attribution
from app.services.benchmark_calculation_service import calculate_benchmark_artifacts
from app.services.execution_lifecycle_service import (
    complete_execution_with_lineage,
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from app.services.mwr_mode_service import resolve_mwr_request
from app.services.stateful_execution_policy_service import (
    finalize_resolved_stateful_execution,
    replay_promoted_stateful_async_execution,
)
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)
from app.services.twr_mode_service import resolve_twr_request
from core.envelope import Audit, Diagnostics, Meta
from core.periods import resolve_periods
from core.repro import generate_canonical_hash, generate_canonical_hash_from_value
from engine.breakdown import generate_performance_breakdowns
from engine.compute import run_calculations
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from engine.mwr import calculate_money_weighted_return
from engine.schema import PortfolioColumns

router = APIRouter(tags=["Performance"])


def _as_numeric(value: object, default=0):
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return numeric


def _get_total_cum_ror(row: pd.Series | None, prefix: str = "") -> float:
    if row is None:
        return 0.0
    long_cum = _as_numeric(row.get(f"{prefix}long_cum_ror", 0))
    short_cum = _as_numeric(row.get(f"{prefix}short_cum_ror", 0))
    return ((1 + long_cum / 100) * (1 + short_cum / 100) - 1) * 100


def _calculate_total_return_from_reset_slice(
    df_slice: pd.DataFrame, daily_results_df: pd.DataFrame
) -> PortfolioReturnDecomposition:
    end_row = df_slice.iloc[-1]
    full_perf_dates = pd.to_datetime(daily_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
    slice_min_date = pd.to_datetime(df_slice[PortfolioColumns.PERF_DATE.value].min()).date()
    day_before_mask = full_perf_dates < slice_min_date
    day_before_row = daily_results_df[day_before_mask].iloc[-1] if day_before_mask.any() else None

    start_cum_base = _as_numeric(
        day_before_row[PortfolioColumns.FINAL_CUM_ROR.value] if day_before_row is not None else 0
    )
    end_cum_base = _as_numeric(end_row[PortfolioColumns.FINAL_CUM_ROR.value])

    start_base_denom = 1 + start_cum_base / 100
    if start_base_denom == 0:
        base_total = end_cum_base
    else:
        base_total = (((1 + end_cum_base / 100) / start_base_denom) - 1) * 100

    if "local_ror" not in df_slice.columns:
        return PortfolioReturnDecomposition(local=base_total, fx=0.0, base=base_total)

    start_cum_local = _get_total_cum_ror(day_before_row, "local_ror_")
    end_cum_local = _get_total_cum_ror(end_row, "local_ror_")

    start_local_denom = 1 + start_cum_local / 100
    if start_local_denom == 0:
        local_total = end_cum_local
    else:
        local_total = (((1 + end_cum_local / 100) / start_local_denom) - 1) * 100

    base_denom_for_fx = 1 + local_total / 100
    if base_denom_for_fx == 0:
        fx_total = 0.0
    else:
        fx_total = (((1 + base_total / 100) / base_denom_for_fx) - 1) * 100

    return PortfolioReturnDecomposition(local=local_total, fx=fx_total, base=base_total)


def _calculate_total_return_from_non_reset_slice(df_slice: pd.DataFrame) -> PortfolioReturnDecomposition:
    daily_ror = pd.to_numeric(df_slice[PortfolioColumns.DAILY_ROR.value], errors="coerce").fillna(0.0)
    base_total = _as_numeric(((1 + daily_ror / 100).prod() - 1) * 100)

    if "local_ror" not in df_slice.columns:
        return PortfolioReturnDecomposition(local=base_total, fx=0.0, base=base_total)

    local_ror = pd.to_numeric(df_slice["local_ror"], errors="coerce").fillna(0.0)
    local_total = _as_numeric(((1 + local_ror / 100).prod() - 1) * 100)
    base_denom_for_fx = 1 + local_total / 100
    if base_denom_for_fx == 0:
        fx_total = 0.0
    else:
        fx_total = _as_numeric((((1 + base_total / 100) / base_denom_for_fx) - 1) * 100)

    return PortfolioReturnDecomposition(local=local_total, fx=fx_total, base=base_total)


def _calculate_total_return_from_slice(
    df_slice: pd.DataFrame, daily_results_df: pd.DataFrame
) -> PortfolioReturnDecomposition:
    if df_slice.empty:
        return PortfolioReturnDecomposition(local=0.0, fx=0.0, base=0.0)

    if df_slice[PortfolioColumns.PERF_RESET.value].any():
        return _calculate_total_return_from_reset_slice(df_slice, daily_results_df)

    return _calculate_total_return_from_non_reset_slice(df_slice)


def _generate_twr_request_hashes(request: TWRAnalyticsRequest, *, engine_version: str) -> tuple[str, str]:
    if request.input_mode == TWRInputMode.STATEFUL:
        canonical_payload = request.model_dump(
            exclude={"performance_start_date"},
            mode="json",
        )
        return generate_canonical_hash_from_value(canonical_payload, engine_version)
    return generate_canonical_hash(request, engine_version)


def _build_resolved_twr_identity_payload(
    *,
    performance_request,
    benchmark_request,
) -> TWRResolvedExecutionRequest:
    return TWRResolvedExecutionRequest(
        portfolio=performance_request,
        benchmark=benchmark_request,
    )


@router.post("/twr", response_model=PerformanceResponse, summary="Calculate Time-Weighted Return")
async def calculate_twr_endpoint(request: TWRAnalyticsRequest):
    """
    Calculates time-weighted return (TWR) for one or more requested periods
    and provides performance breakdowns by requested frequencies.
    """
    settings = get_settings()
    input_fingerprint, calculation_hash = _generate_twr_request_hashes(request, engine_version=settings.APP_VERSION)
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
        requested_window={
            "report_start_date": str(request.report_start_date) if request.report_start_date else None,
            "report_end_date": str(request.report_end_date),
            "requested_periods": [analysis.period.value for analysis in request.analyses],
        },
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    execution_registry.mark_running(request.calculation_id)
    execution_stage_started = False
    lineage_stage_started = False

    try:
        resolved_request = await resolve_twr_request(request, settings=settings)
        performance_request = resolved_request.performance_request
        resolved_twr_identity_payload = _build_resolved_twr_identity_payload(
            performance_request=performance_request,
            benchmark_request=resolved_request.benchmark_request,
        )
        if resolved_request.input_mode == TWRInputMode.STATEFUL or resolved_request.benchmark_request is not None:
            input_fingerprint, calculation_hash = generate_canonical_hash_from_value(
                resolved_twr_identity_payload,
                settings.APP_VERSION,
            )
            execution_registry.update_execution_identity(
                request.calculation_id,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            )
        execution_registry.start_stage(request.calculation_id, "execution")
        execution_stage_started = True
        periods_to_resolve = [analysis.period for analysis in performance_request.analyses]
        freqs_by_period = {analysis.period.value: analysis.frequencies for analysis in performance_request.analyses}

        as_of_date = performance_request.report_end_date
        resolved_periods = resolve_periods(periods_to_resolve, as_of_date, performance_request.performance_start_date)

        if not resolved_periods:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid periods could be resolved.")

        master_start_date = min(p.start_date for p in resolved_periods)
        master_end_date = max(p.end_date for p in resolved_periods)

        engine_config = create_engine_config(performance_request, master_start_date, master_end_date)
        engine_df = create_engine_dataframe([item.model_dump() for item in performance_request.valuation_points])
        daily_results_df, engine_diagnostics = run_calculations(engine_df, engine_config)
        benchmark_artifacts = (
            calculate_benchmark_artifacts(resolved_request.benchmark_request)
            if resolved_request.benchmark_request is not None
            else None
        )

        results_by_period = {}
        daily_results_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
            daily_results_df[PortfolioColumns.PERF_DATE.value]
        ).dt.date

        for period in resolved_periods:
            period_slice_df = daily_results_df[
                (daily_results_df[PortfolioColumns.PERF_DATE.value] >= period.start_date)
                & (daily_results_df[PortfolioColumns.PERF_DATE.value] <= period.end_date)
            ].copy()

            if period_slice_df.empty:
                continue

            requested_frequencies_for_period = freqs_by_period.get(period.name, [])
            breakdowns_data = generate_performance_breakdowns(
                period_slice_df,
                requested_frequencies_for_period,
                performance_request.annualization,
                performance_request.output.include_cumulative,
                performance_request.rounding_precision,
            )
            formatted_breakdowns = format_breakdowns_for_response(
                breakdowns_data, period_slice_df, performance_request.output.include_timeseries
            )

            period_return_summary = _calculate_total_return_from_slice(period_slice_df, daily_results_df)
            period_result = SinglePeriodPerformanceResult(
                breakdowns=formatted_breakdowns, portfolio_return=period_return_summary
            )

            if performance_request.reset_policy.emit and engine_diagnostics.resets:
                period_result.reset_events = [
                    event
                    for event in build_reset_events(engine_diagnostics)
                    if period.start_date <= event.date <= period.end_date
                ]

            results_by_period[period.name] = period_result

    except InvalidEngineInputError as e:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"Invalid Input: {e.message}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid Input: {e.message}")
    except EngineCalculationError as e:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"Calculation Error: {e.message}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Calculation Error: {e.message}")
    except HTTPException:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message="HTTPException raised during TWR execution.",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise
    except Exception as e:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected server error occurred: {str(e)}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected server error occurred: {str(e)}",
        )

    meta = Meta(
        calculation_id=request.calculation_id,
        engine_version=settings.APP_VERSION,
        precision_mode=performance_request.precision_mode,
        calendar=performance_request.calendar,
        annualization=performance_request.annualization,
        periods={
            "requested": [p.value for p in periods_to_resolve],
            "master_start": str(master_start_date),
            "master_end": str(master_end_date),
        },
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        report_ccy=engine_config.report_ccy,
    )
    diagnostics = build_performance_diagnostics(engine_diagnostics)
    audit = Audit(
        counts={"input_rows": len(performance_request.valuation_points), "output_rows": len(daily_results_df)}
    )

    benchmark_response = None
    if resolved_request.benchmark_request is not None and benchmark_artifacts is not None:
        benchmark_mode = resolved_request.benchmark_input_mode or BenchmarkInputMode.STATELESS
        benchmark_response = TWRBenchmarkResponse(
            benchmark_id=resolved_request.resolved_benchmark_id or resolved_request.benchmark_request.benchmark_id,
            benchmark_currency=resolved_request.benchmark_request.benchmark_currency,
            input_mode=benchmark_mode,
            return_source=request.benchmark.return_source if request.benchmark is not None else "calculated",
            results_by_period=benchmark_artifacts.results_by_period,
        )

    response_model = PerformanceResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        input_mode=request.input_mode,
        results_by_period=results_by_period,
        benchmark=benchmark_response,
        meta=meta,
        diagnostics=diagnostics,
        audit=audit,
    )

    calculation_details = {"twr_calculation_details.csv": daily_results_df}
    execution_details = {
        "input_rows": len(performance_request.valuation_points),
        "output_rows": len(daily_results_df),
    }
    if benchmark_artifacts is not None:
        execution_details["benchmark_daily_returns"] = len(benchmark_artifacts.daily_returns_df)
        execution_details["benchmark_component_contributions"] = len(
            benchmark_artifacts.component_contributions_df
        )
        calculation_details["benchmark_daily_returns.csv"] = benchmark_artifacts.daily_returns_df
        calculation_details["benchmark_component_contributions.csv"] = (
            benchmark_artifacts.component_contributions_df
        )

    complete_execution_with_lineage(
        calculation_id=request.calculation_id,
        calculation_type="TWR",
        request_model=(
            resolved_twr_identity_payload
            if resolved_request.input_mode == TWRInputMode.STATEFUL or resolved_request.benchmark_request is not None
            else request
        ),
        response_model=response_model,
        execution_details=execution_details,
        calculation_details=calculation_details,
    )

    return response_model


@router.post("/mwr", response_model=MoneyWeightedReturnResponse, summary="Calculate Money-Weighted Return")
async def calculate_mwr_endpoint(request: MoneyWeightedReturnAnalyticsRequest):
    """Calculates the money-weighted return (MWR) for a portfolio over a given period."""
    active_settings = get_settings()
    input_fingerprint, calculation_hash = generate_canonical_hash(request, active_settings.APP_VERSION)
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type="MWR",
        portfolio_id=request.portfolio_id,
        requested_window={
            "as_of": str(request.as_of),
            "start_date": (
                str(request.stateful_input.window_start_date)
                if request.input_mode == MWRInputMode.STATEFUL and request.stateful_input is not None
                else str(request.start_date)
                if request.start_date is not None
                else None
            ),
        },
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    execution_registry.mark_running(request.calculation_id)
    execution_stage_started = False
    lineage_stage_started = False

    try:
        resolved_request = await resolve_mwr_request(request, settings=active_settings)
        mwr_request = resolved_request.mwr_request
        if resolved_request.input_mode == MWRInputMode.STATEFUL:
            input_fingerprint, calculation_hash = generate_canonical_hash(
                mwr_request,
                active_settings.APP_VERSION,
            )
            execution_registry.update_execution_identity(
                request.calculation_id,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            )
        execution_registry.start_stage(request.calculation_id, "execution")
        execution_stage_started = True
        mwr_result = calculate_money_weighted_return(
            begin_mv=mwr_request.begin_mv,
            end_mv=mwr_request.end_mv,
            cash_flows=mwr_request.cash_flows,
            calculation_method=mwr_request.mwr_method,
            annualization=mwr_request.annualization,
            as_of=mwr_request.as_of,
            start_date=mwr_request.start_date,
        )
    except HTTPException:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message="HTTPException raised during MWR execution.",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise
    except Exception as e:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected error occurred during MWR calculation: {str(e)}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during MWR calculation: {str(e)}",
        )

    meta = Meta(
        calculation_id=request.calculation_id,
        engine_version=active_settings.APP_VERSION,
        precision_mode=mwr_request.precision_mode,
        annualization=mwr_request.annualization,
        calendar=mwr_request.calendar,
        periods={"type": "EXPLICIT", "start": str(mwr_result.start_date), "end": str(mwr_result.end_date)},
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    diagnostics = Diagnostics(
        nip_days=0,
        reset_days=0,
        effective_period_start=mwr_result.start_date,
        notes=mwr_result.notes,
    )
    audit = Audit(counts={"cashflows": len(mwr_request.cash_flows)})

    response_payload = {
        "calculation_id": request.calculation_id,
        "portfolio_id": request.portfolio_id,
        "input_mode": request.input_mode,
        "money_weighted_return": mwr_result.mwr,
        "mwr_annualized": mwr_result.mwr_annualized,
        "method": mwr_result.method,
        "start_date": mwr_result.start_date,
        "end_date": mwr_result.end_date,
        "notes": mwr_result.notes,
        "convergence": mwr_result.convergence,
        "meta": meta,
        "diagnostics": diagnostics,
        "audit": audit,
    }

    response_model = MoneyWeightedReturnResponse.model_validate(response_payload)

    lineage_df_data = [
        {"date": str(mwr_request.start_date or mwr_request.as_of), "type": "begin_mv", "amount": mwr_request.begin_mv}
    ]
    lineage_df_data.extend(
        [{"date": str(cf.date), "type": "cash_flow", "amount": cf.amount} for cf in mwr_request.cash_flows]
    )
    lineage_df_data.append({"date": str(mwr_request.as_of), "type": "end_mv", "amount": mwr_request.end_mv})
    lineage_df = pd.DataFrame(lineage_df_data)

    complete_execution_with_lineage(
        calculation_id=request.calculation_id,
        calculation_type="MWR",
        request_model=mwr_request if request.input_mode == MWRInputMode.STATEFUL else request,
        response_model=response_model,
        execution_details={"cashflows": len(mwr_request.cash_flows)},
        calculation_details={"mwr_cashflow_schedule.csv": lineage_df},
    )

    return response_model


@router.post(
    "/attribution",
    response_model=AttributionResponse | AttributionAcceptedResponse,
    summary="Calculate Multi-Level Performance Attribution",
)
async def calculate_attribution_endpoint(request: AttributionAnalyticsRequest) -> AttributionResponse | JSONResponse:
    """
    Calculates multi-level, Brinson-style performance attribution, decomposing
    active return into allocation, selection, and interaction effects.
    """
    active_settings = get_settings()
    input_fingerprint, calculation_hash = generate_canonical_hash(request, active_settings.APP_VERSION)
    source_request_fingerprint = input_fingerprint
    requested_window = _build_attribution_execution_window(
        request,
        input_count=_attribution_input_count(request),
    )
    if _should_offload_attribution(request):
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type="Attribution",
            portfolio_id=request.portfolio_id,
            requested_window=requested_window,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=request.model_dump(mode="json"),
            offload_reason=(
                "long_window_stateful_attribution"
                if request.input_mode == AttributionInputMode.STATEFUL
                else "large_attribution_input_set"
            ),
            accepted_response_factory=_accepted_attribution_response,
        )

    if request.input_mode == AttributionInputMode.STATEFUL:
        replay_response = replay_promoted_stateful_async_execution(
            calculation_id=request.calculation_id,
            analytics_type="Attribution",
            source_request_fingerprint=source_request_fingerprint,
            accepted_response_factory=_accepted_attribution_response,
        )
        if replay_response is not None:
            return replay_response
        requested_window = _build_attribution_execution_window(
            request,
            input_count=_attribution_input_count(request),
            source_request_fingerprint=source_request_fingerprint,
        )

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type="Attribution",
        portfolio_id=request.portfolio_id,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )

    try:
        resolved = await resolve_attribution_request(request, settings=active_settings)
        if resolved.input_mode == AttributionInputMode.STATEFUL:
            input_fingerprint, calculation_hash = generate_canonical_hash(
                resolved.attribution_request,
                active_settings.APP_VERSION,
            )
            requested_window = _build_attribution_execution_window(
                request,
                input_count=resolved.input_count,
                source_request_fingerprint=source_request_fingerprint,
            )
            accepted_response = finalize_resolved_stateful_execution(
                calculation_id=request.calculation_id,
                analytics_type="Attribution",
                requested_window=requested_window,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
                resolved_request_payload=resolved.attribution_request.model_dump(mode="json"),
                should_offload=_should_offload_resolved_attribution(resolved.input_count),
                offload_reason="large_resolved_stateful_attribution",
                accepted_response_factory=_accepted_attribution_response,
            )
            if accepted_response is not None:
                return accepted_response
        return calculate_attribution(
            resolved.attribution_request,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            input_mode=resolved.input_mode,
        )
    except HTTPException as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc.detail),
        )
        raise
    except Exception as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected error occurred during attribution request resolution: {exc}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during attribution request resolution: {exc}",
        ) from exc


def _attribution_input_count(request: AttributionAnalyticsRequest | AttributionRequest) -> int:
    input_mode = getattr(request, "input_mode", AttributionInputMode.STATELESS)
    if input_mode == AttributionInputMode.STATEFUL:
        return 0
    stateless_input = getattr(request, "stateless_input", None)
    if stateless_input is not None:
        return (
            len(stateless_input.instruments_data or [])
            + len(stateless_input.portfolio_groups_data or [])
            + len(stateless_input.benchmark_groups_data)
        )
    return (
        len(request.instruments_data or [])
        + len(request.portfolio_groups_data or [])
        + len(request.benchmark_groups_data or [])
    )


def _should_offload_attribution(request: AttributionAnalyticsRequest | AttributionRequest) -> bool:
    active_settings = get_settings()
    input_mode = getattr(request, "input_mode", AttributionInputMode.STATELESS)
    if input_mode == AttributionInputMode.STATEFUL:
        return (
            request.report_end_date - request.report_start_date
        ).days >= active_settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS
    return _attribution_input_count(request) >= active_settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT


def _should_offload_resolved_attribution(input_count: int) -> bool:
    active_settings = get_settings()
    return input_count >= active_settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT


def _build_attribution_execution_window(
    request: AttributionAnalyticsRequest | AttributionRequest,
    *,
    input_count: int,
    source_request_fingerprint: str | None = None,
) -> dict[str, object]:
    requested_window = {
        "report_start_date": str(request.report_start_date),
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "input_count": input_count,
        "mode": request.mode.value,
        "group_by": request.group_by,
        "input_mode": getattr(request, "input_mode", AttributionInputMode.STATELESS).value,
    }
    if source_request_fingerprint is not None:
        requested_window["source_request_fingerprint"] = source_request_fingerprint
    return requested_window


def _accepted_attribution_response(calculation_id) -> AttributionAcceptedResponse:
    return AttributionAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/attribution/results/{calculation_id}",
    )


@router.get(
    "/attribution/results/{calculation_id}",
    response_model=AttributionResponse | AttributionAcceptedResponse,
    summary="Retrieve async attribution result",
)
async def get_attribution_result(calculation_id: UUID) -> AttributionResponse | JSONResponse:
    return resolve_async_result(
        calculation_id=calculation_id,
        response_model=AttributionResponse,
        accepted_response_factory=_accepted_attribution_response,
        not_found_detail="Async attribution result not found for the given calculation_id.",
        failed_detail="Async attribution execution failed.",
    )
