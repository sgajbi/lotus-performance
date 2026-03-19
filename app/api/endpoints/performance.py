# app/api/endpoints/performance.py
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest, AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.attribution_responses import AttributionAcceptedResponse, AttributionResponse
from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest, MWRInputMode
from app.models.mwr_responses import MoneyWeightedReturnResponse
from app.models.responses import PerformanceResponse, TWRAcceptedResponse
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode, TWRResolvedExecutionRequest
from app.services.async_result_service import resolve_async_result
from app.services.attribution_mode_service import resolve_attribution_request
from app.services.attribution_service import calculate_attribution
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
from app.services.twr_service import calculate_twr_response
from core.envelope import Audit, Diagnostics, Meta
from core.repro import generate_canonical_hash, generate_canonical_hash_from_value
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from engine.mwr import calculate_money_weighted_return

router = APIRouter(tags=["Performance"])


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

def _twr_benchmark_requested(request: TWRAnalyticsRequest) -> bool:
    return request.include_benchmark or request.benchmark is not None


def _twr_requested_benchmark_input_mode(request: TWRAnalyticsRequest) -> str | None:
    if request.benchmark is not None:
        return request.benchmark.input_mode.value
    if request.include_benchmark and request.input_mode == TWRInputMode.STATEFUL:
        return BenchmarkInputMode.STATEFUL.value
    return None


def _twr_requested_benchmark_return_source(request: TWRAnalyticsRequest) -> str | None:
    if not _twr_benchmark_requested(request):
        return None
    if request.benchmark is not None:
        return request.benchmark.return_source.value
    return BenchmarkReturnSource.CALCULATED.value


def _twr_requested_benchmark_work_units(request: TWRAnalyticsRequest) -> int:
    if request.benchmark is None or request.benchmark.input_mode != BenchmarkInputMode.STATELESS:
        return 0
    stateless_input = request.benchmark.stateless_input
    if stateless_input is None:
        return 0
    if request.benchmark.return_source == BenchmarkReturnSource.CALCULATED:
        return len(stateless_input.component_observations) or len(stateless_input.component_price_points)
    return len(stateless_input.benchmark_return_points)


def _twr_requested_input_count(request: TWRAnalyticsRequest) -> int:
    valuation_points = (
        len(request.stateless_input.valuation_points)
        if request.stateless_input is not None
        else len(request.valuation_points)
    )
    return valuation_points + _twr_requested_benchmark_work_units(request)


def _twr_resolved_benchmark_work_units(benchmark_request) -> int:
    if benchmark_request is None:
        return 0
    return len(benchmark_request.component_observations) or len(benchmark_request.benchmark_return_points)


def _twr_resolved_input_count(performance_request, benchmark_request) -> int:
    return len(performance_request.valuation_points) + _twr_resolved_benchmark_work_units(benchmark_request)


def _should_preemptively_offload_stateful_twr(request: TWRAnalyticsRequest) -> bool:
    active_settings = get_settings()
    return (
        request.input_mode == TWRInputMode.STATEFUL
        and (request.report_end_date - request.performance_start_date).days >= active_settings.TWR_EXECUTOR_WINDOW_DAYS
    )


def _should_offload_twr(request: TWRAnalyticsRequest) -> bool:
    active_settings = get_settings()
    return _should_preemptively_offload_stateful_twr(request) or (
        _twr_requested_input_count(request) >= active_settings.TWR_EXECUTOR_INPUT_COUNT
    )


def _should_offload_resolved_twr(input_count: int) -> bool:
    active_settings = get_settings()
    return input_count >= active_settings.TWR_EXECUTOR_INPUT_COUNT


def _build_twr_execution_window(
    request: TWRAnalyticsRequest,
    *,
    input_count: int,
    source_request_fingerprint: str | None = None,
    benchmark_id: str | None = None,
    benchmark_work_units: int | None = None,
) -> dict[str, object]:
    requested_window: dict[str, object] = {
        "performance_start_date": str(request.performance_start_date),
        "report_start_date": str(request.report_start_date) if request.report_start_date else None,
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "input_mode": request.input_mode.value,
        "include_benchmark": request.include_benchmark,
        "input_count": input_count,
    }
    if source_request_fingerprint is not None:
        requested_window["source_request_fingerprint"] = source_request_fingerprint
    requested_benchmark_id = benchmark_id or (request.benchmark.benchmark_id if request.benchmark is not None else None)
    if requested_benchmark_id is not None:
        requested_window["benchmark_id"] = requested_benchmark_id
    benchmark_input_mode = _twr_requested_benchmark_input_mode(request)
    if benchmark_input_mode is not None:
        requested_window["benchmark_input_mode"] = benchmark_input_mode
    benchmark_return_source = _twr_requested_benchmark_return_source(request)
    if benchmark_return_source is not None:
        requested_window["benchmark_return_source"] = benchmark_return_source
    if benchmark_work_units is not None:
        requested_window["benchmark_work_units"] = benchmark_work_units
    return requested_window


def _accepted_twr_response(calculation_id) -> TWRAcceptedResponse:
    return TWRAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/twr/results/{calculation_id}",
    )


@router.post("/twr", response_model=PerformanceResponse | TWRAcceptedResponse, summary="Calculate Time-Weighted Return")
async def calculate_twr_endpoint(request: TWRAnalyticsRequest) -> PerformanceResponse | JSONResponse:
    """
    Calculates time-weighted return (TWR) for one or more requested periods
    and provides performance breakdowns by requested frequencies.
    """
    settings = get_settings()
    input_fingerprint, calculation_hash = _generate_twr_request_hashes(request, engine_version=settings.APP_VERSION)
    source_request_fingerprint = input_fingerprint
    requested_window = _build_twr_execution_window(
        request,
        input_count=_twr_requested_input_count(request),
    )
    if _should_offload_twr(request):
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type="TWR",
            portfolio_id=request.portfolio_id,
            requested_window=requested_window,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=request.model_dump(mode="json"),
            offload_reason=(
                "long_window_stateful_twr"
                if request.input_mode == TWRInputMode.STATEFUL
                else "large_twr_input_set"
            ),
            accepted_response_factory=_accepted_twr_response,
        )

    if request.input_mode == TWRInputMode.STATEFUL:
        replay_response = replay_promoted_stateful_async_execution(
            calculation_id=request.calculation_id,
            analytics_type="TWR",
            source_request_fingerprint=source_request_fingerprint,
            accepted_response_factory=_accepted_twr_response,
        )
        if replay_response is not None:
            return replay_response
        requested_window = _build_twr_execution_window(
            request,
            input_count=_twr_requested_input_count(request),
            source_request_fingerprint=source_request_fingerprint,
        )

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )

    try:
        resolved_request = await resolve_twr_request(request, settings=settings)
        performance_request = resolved_request.performance_request
        resolved_twr_identity_payload = _build_resolved_twr_identity_payload(
            performance_request=performance_request,
            benchmark_request=resolved_request.benchmark_request,
        )
        request_artifact_model = (
            resolved_twr_identity_payload
            if resolved_request.input_mode == TWRInputMode.STATEFUL or resolved_request.benchmark_request is not None
            else request
        )
        resolved_input_count = _twr_resolved_input_count(
            performance_request,
            resolved_request.benchmark_request,
        )
        benchmark_work_units = _twr_resolved_benchmark_work_units(resolved_request.benchmark_request)
        if resolved_request.input_mode == TWRInputMode.STATEFUL or resolved_request.benchmark_request is not None:
            input_fingerprint, calculation_hash = generate_canonical_hash_from_value(
                resolved_twr_identity_payload,
                settings.APP_VERSION,
            )
            if request.input_mode == TWRInputMode.STATEFUL:
                accepted_response = finalize_resolved_stateful_execution(
                    calculation_id=request.calculation_id,
                    analytics_type="TWR",
                    requested_window=_build_twr_execution_window(
                        request,
                        input_count=resolved_input_count,
                        source_request_fingerprint=source_request_fingerprint,
                        benchmark_id=resolved_request.resolved_benchmark_id,
                        benchmark_work_units=benchmark_work_units,
                    ),
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                    resolved_request_payload={
                        "resolved_request": resolved_twr_identity_payload.model_dump(mode="json"),
                        "source_input_mode": resolved_request.input_mode.value,
                        "benchmark_input_mode": (
                            resolved_request.benchmark_input_mode.value
                            if resolved_request.benchmark_input_mode is not None
                            else None
                        ),
                        "resolved_benchmark_id": resolved_request.resolved_benchmark_id,
                        "benchmark_return_source": (
                            request.benchmark.return_source.value
                            if request.benchmark is not None
                            else BenchmarkReturnSource.CALCULATED.value
                        ),
                        "portfolio_id": request.portfolio_id,
                    },
                    should_offload=_should_offload_resolved_twr(resolved_input_count),
                    offload_reason="large_resolved_stateful_twr",
                    accepted_response_factory=_accepted_twr_response,
                )
                if accepted_response is not None:
                    return accepted_response
            else:
                execution_registry.update_execution_identity(
                    request.calculation_id,
                    input_fingerprint=input_fingerprint,
                    calculation_hash=calculation_hash,
                )
        return calculate_twr_response(
            performance_request,
            portfolio_id=request.portfolio_id,
            input_mode=resolved_request.input_mode,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            engine_version=settings.APP_VERSION,
            request_artifact_model=request_artifact_model,
            benchmark_request=resolved_request.benchmark_request,
            benchmark_input_mode=resolved_request.benchmark_input_mode,
            resolved_benchmark_id=resolved_request.resolved_benchmark_id,
            benchmark_return_source=(
                request.benchmark.return_source if request.benchmark is not None else BenchmarkReturnSource.CALCULATED
            ),
        )
    except InvalidEngineInputError as e:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"Invalid Input: {e.message}",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid Input: {e.message}")
    except EngineCalculationError as e:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"Calculation Error: {e.message}",
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Calculation Error: {e.message}")
    except HTTPException:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message="HTTPException raised during TWR execution.",
        )
        raise
    except Exception as e:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected server error occurred: {str(e)}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected server error occurred: {str(e)}",
        )


@router.get(
    "/twr/results/{calculation_id}",
    response_model=PerformanceResponse | TWRAcceptedResponse,
    summary="Retrieve async TWR result",
)
async def get_twr_result(calculation_id: UUID) -> PerformanceResponse | JSONResponse:
    return resolve_async_result(
        calculation_id=calculation_id,
        response_model=PerformanceResponse,
        accepted_response_factory=_accepted_twr_response,
        not_found_detail="Async TWR result not found for the given calculation_id.",
        failed_detail="Async TWR execution failed.",
    )


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
