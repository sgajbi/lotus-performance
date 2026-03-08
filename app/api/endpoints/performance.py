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
from app.models.attribution_requests import AttributionRequest
from app.models.attribution_responses import AttributionAcceptedResponse, AttributionResponse
from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.models.mwr_responses import MoneyWeightedReturnResponse
from app.models.requests import PerformanceRequest
from app.models.responses import (
    PerformanceResponse,
    PortfolioReturnDecomposition,
    ResetEvent,
    SinglePeriodPerformanceResult,
)
from app.services.async_result_store import AsyncResultStatus, async_result_store
from app.services.attribution_service import calculate_attribution
from app.services.compute_job_store import ComputeJobStatus, compute_job_store
from app.services.execution_registry import execution_registry
from app.services.lineage_service import lineage_service
from core.envelope import Audit, Diagnostics, Meta
from core.periods import resolve_periods
from core.repro import generate_canonical_hash
from engine.breakdown import generate_performance_breakdowns
from engine.compute import run_calculations
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from engine.mwr import calculate_money_weighted_return
from engine.schema import PortfolioColumns

router = APIRouter(tags=["Performance"])
settings = get_settings()


def _record_execution_failure(
    *,
    calculation_id,
    message: str,
    execution_stage_started: bool = False,
    lineage_stage_started: bool = False,
) -> None:
    if lineage_stage_started:
        execution_registry.fail_stage(calculation_id, "lineage_materialization", message)
    elif execution_stage_started:
        execution_registry.fail_stage(calculation_id, "execution", message)
    execution_registry.mark_failed(calculation_id, message)


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


@router.post("/twr", response_model=PerformanceResponse, summary="Calculate Time-Weighted Return")
async def calculate_twr_endpoint(request: PerformanceRequest):
    """
    Calculates time-weighted return (TWR) for one or more requested periods
    and provides performance breakdowns by requested frequencies.
    """
    input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)
    execution_registry.create_execution(
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
        execution_registry.start_stage(request.calculation_id, "execution")
        execution_stage_started = True
        periods_to_resolve = [analysis.period for analysis in request.analyses]
        freqs_by_period = {analysis.period.value: analysis.frequencies for analysis in request.analyses}

        as_of_date = request.report_end_date
        resolved_periods = resolve_periods(periods_to_resolve, as_of_date, request.performance_start_date)

        if not resolved_periods:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid periods could be resolved.")

        master_start_date = min(p.start_date for p in resolved_periods)
        master_end_date = max(p.end_date for p in resolved_periods)

        engine_config = create_engine_config(request, master_start_date, master_end_date)
        engine_df = create_engine_dataframe([item.model_dump() for item in request.valuation_points])
        daily_results_df, diagnostics_data = run_calculations(engine_df, engine_config)

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
                request.annualization,
                request.output.include_cumulative,
                request.rounding_precision,
            )
            formatted_breakdowns = format_breakdowns_for_response(
                breakdowns_data, period_slice_df, request.output.include_timeseries
            )

            period_return_summary = _calculate_total_return_from_slice(period_slice_df, daily_results_df)
            period_result = SinglePeriodPerformanceResult(
                breakdowns=formatted_breakdowns, portfolio_return=period_return_summary
            )

            if request.reset_policy.emit and diagnostics_data.get("resets"):
                period_result.reset_events = [
                    ResetEvent(**event)
                    for event in diagnostics_data["resets"]
                    if period.start_date <= event["date"] <= period.end_date
                ]

            results_by_period[period.name] = period_result

    except InvalidEngineInputError as e:
        _record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"Invalid Input: {e.message}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid Input: {e.message}")
    except EngineCalculationError as e:
        _record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"Calculation Error: {e.message}",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Calculation Error: {e.message}")
    except HTTPException:
        _record_execution_failure(
            calculation_id=request.calculation_id,
            message="HTTPException raised during TWR execution.",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise
    except Exception as e:
        _record_execution_failure(
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
        precision_mode=request.precision_mode,
        calendar=request.calendar,
        annualization=request.annualization,
        periods={
            "requested": [p.value for p in periods_to_resolve],
            "master_start": str(master_start_date),
            "master_end": str(master_end_date),
        },
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        report_ccy=engine_config.report_ccy,
    )
    diagnostics = Diagnostics(
        nip_days=diagnostics_data.get("nip_days", 0),
        reset_days=diagnostics_data.get("reset_days", 0),
        effective_period_start=diagnostics_data.get("effective_period_start"),
        notes=diagnostics_data.get("notes", []),
        policy=diagnostics_data.get("policy"),
        samples=diagnostics_data.get("samples"),
    )
    audit = Audit(counts={"input_rows": len(request.valuation_points), "output_rows": len(daily_results_df)})

    response_model = PerformanceResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        results_by_period=results_by_period,
        meta=meta,
        diagnostics=diagnostics,
        audit=audit,
    )

    execution_registry.complete_stage(
        request.calculation_id,
        "execution",
        details={"input_rows": len(request.valuation_points), "output_rows": len(daily_results_df)},
    )
    execution_stage_started = False
    execution_registry.start_stage(request.calculation_id, "lineage_materialization")
    lineage_stage_started = True
    lineage_service.enqueue_capture(
        calculation_id=request.calculation_id,
        calculation_type="TWR",
        request_model=request,
        response_model=response_model,
        calculation_details={"twr_calculation_details.csv": daily_results_df},
    )
    execution_registry.mark_complete(request.calculation_id)

    return response_model


@router.post("/mwr", response_model=MoneyWeightedReturnResponse, summary="Calculate Money-Weighted Return")
async def calculate_mwr_endpoint(request: MoneyWeightedReturnRequest):
    """Calculates the money-weighted return (MWR) for a portfolio over a given period."""
    input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="MWR",
        portfolio_id=request.portfolio_id,
        requested_window={"as_of": str(request.as_of)},
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    execution_registry.mark_running(request.calculation_id)
    execution_stage_started = False
    lineage_stage_started = False

    try:
        execution_registry.start_stage(request.calculation_id, "execution")
        execution_stage_started = True
        mwr_result = calculate_money_weighted_return(
            begin_mv=request.begin_mv,
            end_mv=request.end_mv,
            cash_flows=request.cash_flows,
            calculation_method=request.mwr_method,
            annualization=request.annualization,
            as_of=request.as_of,
        )
    except HTTPException:
        _record_execution_failure(
            calculation_id=request.calculation_id,
            message="HTTPException raised during MWR execution.",
            execution_stage_started=execution_stage_started,
            lineage_stage_started=lineage_stage_started,
        )
        raise
    except Exception as e:
        _record_execution_failure(
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
        engine_version=settings.APP_VERSION,
        precision_mode=request.precision_mode,
        annualization=request.annualization,
        calendar=request.calendar,
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
    audit = Audit(counts={"cashflows": len(request.cash_flows)})

    response_payload = {
        "calculation_id": request.calculation_id,
        "portfolio_id": request.portfolio_id,
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

    lineage_df_data = [{"date": str(request.as_of), "type": "begin_mv", "amount": request.begin_mv}]
    lineage_df_data.extend(
        [{"date": str(cf.date), "type": "cash_flow", "amount": cf.amount} for cf in request.cash_flows]
    )
    lineage_df_data.append({"date": str(request.as_of), "type": "end_mv", "amount": request.end_mv})
    lineage_df = pd.DataFrame(lineage_df_data)

    execution_registry.complete_stage(
        request.calculation_id,
        "execution",
        details={"cashflows": len(request.cash_flows)},
    )
    execution_stage_started = False
    execution_registry.start_stage(request.calculation_id, "lineage_materialization")
    lineage_stage_started = True
    lineage_service.enqueue_capture(
        calculation_id=request.calculation_id,
        calculation_type="MWR",
        request_model=request,
        response_model=response_model,
        calculation_details={"mwr_cashflow_schedule.csv": lineage_df},
    )
    execution_registry.mark_complete(request.calculation_id)

    return response_model


@router.post(
    "/attribution",
    response_model=AttributionResponse | AttributionAcceptedResponse,
    summary="Calculate Multi-Level Performance Attribution",
)
async def calculate_attribution_endpoint(request: AttributionRequest) -> AttributionResponse | JSONResponse:
    """
    Calculates multi-level, Brinson-style performance attribution, decomposing
    active return into allocation, selection, and interaction effects.
    """
    input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)
    execution_registry.create_schema()
    compute_job_store.create_schema()
    async_result_store.create_schema()
    execution_mode = "async" if _should_offload_attribution(request) else "sync"
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="Attribution",
        portfolio_id=request.portfolio_id,
        execution_mode=execution_mode,
        requested_window={
            "report_start_date": str(request.report_start_date),
            "report_end_date": str(request.report_end_date),
            "requested_periods": [analysis.period.value for analysis in request.analyses],
            "input_count": _attribution_input_count(request),
            "mode": request.mode.value,
            "group_by": request.group_by,
        },
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    if execution_mode == "async":
        execution_registry.start_stage(request.calculation_id, "submission")
        compute_job_store.enqueue_job(
            calculation_id=request.calculation_id,
            analytics_type="Attribution",
            request_payload=request.model_dump(mode="json"),
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "submission",
            details={"offload_reason": "large_attribution_input_set"},
        )
        accepted = _accepted_attribution_response(request.calculation_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump(mode="json"))

    return calculate_attribution(
        request,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )


def _attribution_input_count(request: AttributionRequest) -> int:
    return (
        len(request.instruments_data or [])
        + len(request.portfolio_groups_data or [])
        + len(request.benchmark_groups_data)
    )


def _should_offload_attribution(request: AttributionRequest) -> bool:
    return _attribution_input_count(request) >= settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT


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
    async_result = async_result_store.get_result(calculation_id)
    if async_result is not None:
        if async_result.result_status == AsyncResultStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=async_result.error_message or "Async attribution execution failed.",
            )
        return AttributionResponse.model_validate(async_result.response_payload)
    job = compute_job_store.get_job(calculation_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Async attribution result not found for the given calculation_id.",
        )
    if job.job_status in {ComputeJobStatus.PENDING, ComputeJobStatus.LEASED, ComputeJobStatus.RUNNING}:
        accepted = _accepted_attribution_response(calculation_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump(mode="json"))
    if job.job_status == ComputeJobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=job.error_message or "Async attribution execution failed.",
        )
    return AttributionResponse.model_validate(job.response_payload)
