# app/api/endpoints/performance.py
from dataclasses import asdict
from decimal import Decimal
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
from app.models.platform_surfaces import ErrorDetailResponse
from app.models.responses import PerformanceResponse, TWRAcceptedResponse
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode, TWRResolvedExecutionRequest
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.models.workspace_summary_responses import WorkspaceSummaryAcceptedResponse, WorkspaceSummaryResponse
from app.observability import record_mwr_solver_outcome
from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_MWR,
    ANALYTICS_WORKFLOW_TWR,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)
from app.services.async_result_service import resolve_async_result
from app.services.attribution_mode_service import resolve_attribution_request
from app.services.attribution_service import calculate_attribution
from app.services.calculation_supportability_service import (
    build_calculation_supportability,
    record_supportability_metric,
)
from app.services.execution_lifecycle_service import (
    complete_execution_with_lineage,
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from app.services.mwr_mode_service import resolve_mwr_request
from app.services.reproducibility_service import generate_request_fingerprint, generate_value_fingerprint
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
from app.services.workspace_summary_service import calculate_workspace_summary
from core.envelope import Audit, Diagnostics, Meta
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from engine.mwr import calculate_money_weighted_return

router = APIRouter(tags=["Performance"])


def _generate_twr_request_hashes(request: TWRAnalyticsRequest, *, engine_version: str) -> tuple[str, str]:
    if request.input_mode == TWRInputMode.STATEFUL:
        canonical_payload = request.model_dump(
            exclude={"performance_start_date"},
            mode="json",
        )
        return generate_value_fingerprint(canonical_payload, engine_version)
    return generate_request_fingerprint(request, engine_version)


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
        and request.performance_start_date is not None
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
        "performance_start_date": (
            str(request.performance_start_date) if request.performance_start_date is not None else None
        ),
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


def _accepted_workspace_summary_response(calculation_id) -> WorkspaceSummaryAcceptedResponse:
    return WorkspaceSummaryAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/workspace-summary/results/{calculation_id}",
    )


def _workspace_requested_benchmark_work_units(request: WorkspaceSummaryRequest) -> int:
    benchmark = request.benchmark
    if benchmark is None or benchmark.input_mode != BenchmarkInputMode.STATELESS or benchmark.stateless_input is None:
        return 0
    if benchmark.return_source == BenchmarkReturnSource.CALCULATED:
        return len(benchmark.stateless_input.component_observations) or len(
            benchmark.stateless_input.component_price_points
        )
    return len(benchmark.stateless_input.benchmark_return_points)


def _workspace_requested_input_count(request: WorkspaceSummaryRequest) -> int:
    valuation_points = (
        len(request.resolved_stateless_valuation_points()) if request.input_mode == TWRInputMode.STATELESS else 0
    )
    return valuation_points + _workspace_requested_benchmark_work_units(request)


def _workspace_longest_requested_window_days(request: WorkspaceSummaryRequest) -> int:
    if request.input_mode != TWRInputMode.STATEFUL:
        return 0
    if any(period.period.value == "SI" for period in request.periods) and request.performance_start_date is None:
        return 10_000
    from core.workspace_periods import resolve_workspace_periods

    assumed_start = request.performance_start_date or request.report_start_date or request.report_end_date
    resolved_periods = resolve_workspace_periods(
        [item.period for item in request.periods],
        as_of=request.report_end_date,
        performance_start_date=assumed_start,
        explicit_start_date=request.report_start_date,
    )
    return max((period.end_date - period.start_date).days for period in resolved_periods) if resolved_periods else 0


def _should_offload_workspace_summary(request: WorkspaceSummaryRequest) -> bool:
    settings = get_settings()
    return (
        request.input_mode == TWRInputMode.STATEFUL
        and _workspace_longest_requested_window_days(request) >= settings.WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS
    ) or (_workspace_requested_input_count(request) >= settings.WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT)


@router.post(
    "/workspace-summary",
    response_model=WorkspaceSummaryResponse | WorkspaceSummaryAcceptedResponse,
    summary="Calculate interaction-efficient workspace summary analytics",
    description=(
        "Returns a front-office workspace summary for one or more requested horizons in a single "
        "source-owned response. Use this endpoint when a UI or experience API needs coherent "
        "portfolio TWR net/gross, benchmark, active return, MWR, economics, diagnostics, and audit "
        "counts without orchestrating multiple deep-analysis endpoints. Stateless callers supply "
        "valuation observations and optional benchmark input; stateful callers use an empty "
        "stateful_input envelope so lotus-performance can source portfolio and benchmark data from "
        "governed upstream contracts. Large stateful or large-input requests may return 202 with "
        "poll_path and result_path."
    ),
)
def calculate_workspace_summary_endpoint(
    request: WorkspaceSummaryRequest,
) -> WorkspaceSummaryResponse | JSONResponse:
    """Calculates multi-horizon workspace summary analytics in one source-owned response."""
    settings = get_settings()
    input_fingerprint, calculation_hash = generate_request_fingerprint(request, settings.APP_VERSION)
    requested_window = {
        "report_end_date": str(request.report_end_date),
        "requested_periods": [item.period.value for item in request.periods],
        "input_mode": request.input_mode.value,
        "include_benchmark": request.include_benchmark,
        "input_count": _workspace_requested_input_count(request),
        "longest_window_days": _workspace_longest_requested_window_days(request),
    }
    if _should_offload_workspace_summary(request):
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type=ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
            portfolio_id=request.portfolio_id,
            requested_window=requested_window,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=request.model_dump(mode="json"),
            offload_reason=(
                "long_window_stateful_workspace_summary"
                if request.input_mode == TWRInputMode.STATEFUL
                else "large_workspace_summary_input_set"
            ),
            accepted_response_factory=_accepted_workspace_summary_response,
        )
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
        portfolio_id=request.portfolio_id,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    execution_registry.mark_running(request.calculation_id)
    try:
        return calculate_workspace_summary(request, settings=settings)
    except HTTPException as exc:
        record_execution_failure(calculation_id=request.calculation_id, message=str(exc.detail))
        raise
    except Exception as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected server error occurred while calculating workspace summary: {exc}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected server error occurred while calculating workspace summary: {exc}",
        ) from exc


@router.get(
    "/workspace-summary/results/{calculation_id}",
    response_model=WorkspaceSummaryResponse | WorkspaceSummaryAcceptedResponse,
    summary="Retrieve async workspace summary result",
    description=(
        "Retrieves the completed workspace-summary response for an async request, or returns the "
        "accepted envelope while execution remains pending."
    ),
)
async def get_workspace_summary_result(calculation_id: UUID) -> WorkspaceSummaryResponse | JSONResponse:
    return resolve_async_result(
        calculation_id=calculation_id,
        response_model=WorkspaceSummaryResponse,
        accepted_response_factory=_accepted_workspace_summary_response,
        not_found_detail="Async workspace summary result not found for the given calculation_id.",
        failed_detail="Async workspace summary execution failed.",
    )


@router.post(
    "/twr",
    response_model=PerformanceResponse | TWRAcceptedResponse,
    summary="Calculate Time-Weighted Return",
    description=(
        "Calculates portfolio time-weighted return for stateless caller-supplied valuation "
        "points or stateful lotus-core-sourced portfolio analytics inputs. Use this endpoint "
        "for performance measurement where external cash flows must be neutralized and "
        "investment performance must be geometrically linked across one or more requested "
        "analysis periods. Smaller requests return the completed TWR response immediately; "
        "large or long-window stateful requests can return 202 with poll_path and result_path."
    ),
    responses={
        202: {
            "model": TWRAcceptedResponse,
            "description": (
                "Accepted for asynchronous TWR execution. Poll poll_path for execution status "
                "or result_path for the completed TWR response."
            ),
        }
    },
)
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
            analytics_type=ANALYTICS_WORKFLOW_TWR,
            portfolio_id=request.portfolio_id,
            requested_window=requested_window,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=request.model_dump(mode="json"),
            offload_reason=(
                "long_window_stateful_twr" if request.input_mode == TWRInputMode.STATEFUL else "large_twr_input_set"
            ),
            accepted_response_factory=_accepted_twr_response,
        )

    if request.input_mode == TWRInputMode.STATEFUL:
        replay_response = replay_promoted_stateful_async_execution(
            calculation_id=request.calculation_id,
            analytics_type=ANALYTICS_WORKFLOW_TWR,
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
        analytics_type=ANALYTICS_WORKFLOW_TWR,
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
            input_fingerprint, calculation_hash = generate_value_fingerprint(
                resolved_twr_identity_payload,
                settings.APP_VERSION,
            )
            if request.input_mode == TWRInputMode.STATEFUL:
                accepted_response = finalize_resolved_stateful_execution(
                    calculation_id=request.calculation_id,
                    analytics_type=ANALYTICS_WORKFLOW_TWR,
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
    except HTTPException as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc.detail),
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
    description=(
        "Retrieves the result for a TWR request that previously returned 202 Accepted. "
        "Returns the completed PerformanceResponse when execution is complete, or the "
        "accepted envelope while the durable calculation is still pending."
    ),
    responses={
        202: {
            "model": TWRAcceptedResponse,
            "description": "The async TWR calculation is still pending.",
        },
        404: {
            "model": ErrorDetailResponse,
            "description": "No async TWR result exists for the supplied calculation_id.",
            "content": {
                "application/json": {"example": {"detail": "Async TWR result not found for the given calculation_id."}}
            },
        },
    },
)
async def get_twr_result(calculation_id: UUID) -> PerformanceResponse | JSONResponse:
    return resolve_async_result(
        calculation_id=calculation_id,
        response_model=PerformanceResponse,
        accepted_response_factory=_accepted_twr_response,
        not_found_detail="Async TWR result not found for the given calculation_id.",
        failed_detail="Async TWR execution failed.",
    )


@router.post(
    "/mwr",
    response_model=MoneyWeightedReturnResponse,
    summary="Calculate Money-Weighted Return",
    description=(
        "Calculates money-weighted return for the investor capital-timing lens. Use this endpoint when "
        "the question is how the portfolio performed for the client after the size and timing of external "
        "cash flows, deposits, withdrawals, and sourced capital-base adjustments are considered. Use "
        '`input_mode="stateless"` when the caller already owns beginning value, ending value, and the signed '
        "cash-flow schedule; callers with upstream-converted source-currency inputs may supply complete "
        "`source_preconverted_fx_evidence` for every market value and cash flow so the response records "
        "validated FX provenance while the MWR engine still calculates on reporting-currency amounts. "
        'Use `input_mode="stateful"` for lotus-core-sourced portfolio analytics input; '
        "lotus-performance reads the query-control-plane portfolio timeseries, normalizes explicit external "
        "cash flows and cross-observation carry-forward capital breaks into canonical MWR inputs, keeps "
        "operational fees as performance drag rather than investor cash movement, and then runs the requested "
        "`mwr_method`. `XIRR` returns the annual IRR solved from irregular cash-flow dates; "
        "`MODIFIED_DIETZ` returns a period return using dated cash-flow weights; `DIETZ` returns "
        "the midpoint Dietz period return."
    ),
)
async def calculate_mwr_endpoint(request: MoneyWeightedReturnAnalyticsRequest):
    """Calculates the money-weighted return (MWR) for a portfolio over a given period."""
    active_settings = get_settings()
    input_fingerprint, calculation_hash = generate_request_fingerprint(request, active_settings.APP_VERSION)
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_MWR,
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
            input_fingerprint, calculation_hash = generate_request_fingerprint(
                mwr_request,
                active_settings.APP_VERSION,
            )
            execution_registry.update_execution_identity(
                request.calculation_id,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            )
        execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_EXECUTION)
        execution_stage_started = True
        mwr_result = calculate_money_weighted_return(
            begin_mv=mwr_request.begin_mv,
            end_mv=mwr_request.end_mv,
            cash_flows=mwr_request.cash_flows,
            calculation_method=mwr_request.mwr_method,
            annualization=mwr_request.annualization,
            as_of=mwr_request.as_of,
            start_date=mwr_request.start_date,
            solver=mwr_request.solver,
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
    calculation_supportability = build_calculation_supportability(
        input_row_count=len(mwr_request.cash_flows) + 2,
        resolved_period_count=1,
        latest_observation_date=mwr_result.end_date,
        report_end_date=mwr_request.as_of,
        minimum_input_row_count=2,
    )
    record_supportability_metric(operation="mwr", supportability=calculation_supportability)
    record_mwr_solver_outcome(
        input_mode=request.input_mode.value,
        method=mwr_result.method,
        status=mwr_result.status,
        reason_codes=mwr_result.reason_codes,
        fallback_used=mwr_result.fallback_from is not None or mwr_result.is_approximation,
    )
    reporting_currency = (
        resolved_request.currency_evidence.reporting_currency
        if resolved_request.currency_evidence is not None
        else mwr_request.report_ccy or mwr_request.currency
    )

    response_payload = {
        "calculation_id": request.calculation_id,
        "portfolio_id": request.portfolio_id,
        "input_mode": request.input_mode,
        "money_weighted_return": mwr_result.mwr,
        "mwr_annualized": mwr_result.mwr_annualized,
        "method": mwr_result.method,
        "status": mwr_result.status,
        "reason_codes": mwr_result.reason_codes,
        "warnings": mwr_result.warnings,
        "holding_period_return": mwr_result.holding_period_return,
        "is_annualized_primary": mwr_result.is_annualized_primary,
        "fallback_from": mwr_result.fallback_from,
        "fallback_reason": mwr_result.fallback_reason,
        "is_approximation": mwr_result.is_approximation,
        "start_date": mwr_result.start_date,
        "end_date": mwr_result.end_date,
        "notes": mwr_result.notes,
        "convergence": mwr_result.convergence,
        "cashflows_used": mwr_request.cash_flows if mwr_request.emit_cashflows_used else None,
        "reporting_currency": reporting_currency,
        "currency_evidence": (
            _decimal_safe_dataclass_payload(resolved_request.currency_evidence)
            if resolved_request.currency_evidence is not None
            else None
        ),
        "calculation_supportability": calculation_supportability,
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
        calculation_type=ANALYTICS_WORKFLOW_MWR,
        request_model=mwr_request if request.input_mode == MWRInputMode.STATEFUL else request,
        response_model=response_model,
        execution_details={"cashflows": len(mwr_request.cash_flows)},
        calculation_details={"mwr_cashflow_schedule.csv": lineage_df},
    )

    return response_model


def _decimal_safe_dataclass_payload(value: object) -> object:
    payload = asdict(value)
    return _stringify_decimals(payload)


def _stringify_decimals(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_stringify_decimals(item) for item in value]
    if isinstance(value, dict):
        return {key: _stringify_decimals(item) for key, item in value.items()}
    return value


@router.post(
    "/attribution",
    response_model=AttributionResponse | AttributionAcceptedResponse,
    summary="Calculate Multi-Level Performance Attribution",
    description=(
        "Decomposes portfolio active return versus a benchmark into allocation, selection, "
        "interaction, and total effect using Brinson-style attribution. Use this endpoint "
        "when front-office users need to explain whether active performance came from asset "
        "allocation, group or security selection, or the interaction between active weights "
        "and active returns. Stateless callers may supply instrument or pre-aggregated group "
        "inputs. Stateful callers source portfolio positions and benchmark components through "
        "lotus-core analytics-input contracts. Each level returns authoritative total fields "
        "for UI footers and summary-only views; downstream systems should not infer totals by "
        "summing only visible rows."
    ),
    responses={
        202: {
            "model": AttributionAcceptedResponse,
            "description": (
                "Accepted for asynchronous attribution execution. Poll poll_path for execution "
                "status or result_path for the completed attribution response."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "calculation_id": "209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3",
                        "poll_path": "/performance/executions/209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3",
                        "result_path": "/performance/attribution/results/209da27d-f3f4-4e64-97c5-a2eb1d4fe4f3",
                    }
                }
            },
        },
        400: {
            "model": ErrorDetailResponse,
            "description": (
                "Invalid attribution request shape, unsupported resolved period window, or invalid engine input."
            ),
            "content": {"application/json": {"example": {"detail": "Invalid Input: analyses list cannot be empty"}}},
        },
        409: {
            "model": ErrorDetailResponse,
            "description": "Duplicate attribution submission conflict or failed async execution state.",
            "content": {"application/json": {"example": {"detail": "Duplicate submission payload does not match."}}},
        },
        422: {
            "description": (
                "Attribution source contract cannot support the requested calculation, such as missing benchmark "
                "assignment, unsupported stateful mode, missing FX for mixed-currency stateful attribution, or "
                "unsupported grouping dimension."
            ),
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/ErrorDetailResponse"},
                            {"$ref": "#/components/schemas/HTTPValidationError"},
                        ]
                    },
                    "example": {
                        "detail": (
                            "Stateful attribution input requires fx.rates when currency_mode=BOTH and sourced "
                            "positions include currencies different from report_ccy."
                        )
                    },
                }
            },
        },
        500: {
            "model": ErrorDetailResponse,
            "description": "Unexpected attribution request resolution or calculation failure.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "An unexpected error occurred during attribution request resolution: upstream timeout"
                    }
                }
            },
        },
    },
)
async def calculate_attribution_endpoint(request: AttributionAnalyticsRequest) -> AttributionResponse | JSONResponse:
    """
    Calculates multi-level, Brinson-style performance attribution, decomposing
    active return into allocation, selection, and interaction effects.
    """
    active_settings = get_settings()
    input_fingerprint, calculation_hash = generate_request_fingerprint(request, active_settings.APP_VERSION)
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
            input_fingerprint, calculation_hash = generate_request_fingerprint(
                resolved.attribution_request,
                active_settings.APP_VERSION,
            )
            requested_window = _build_attribution_execution_window(
                request,
                input_count=resolved.input_count,
                source_request_fingerprint=source_request_fingerprint,
                benchmark_id=resolved.resolved_benchmark_id,
                benchmark_return_source=resolved.resolved_benchmark_return_source,
            )
            accepted_response = finalize_resolved_stateful_execution(
                calculation_id=request.calculation_id,
                analytics_type="Attribution",
                requested_window=requested_window,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
                resolved_request_payload={
                    "resolved_request": resolved.attribution_request.model_dump(mode="json"),
                    "source_input_mode": resolved.input_mode.value,
                    "resolved_benchmark_id": resolved.resolved_benchmark_id,
                    "resolved_benchmark_return_source": resolved.resolved_benchmark_return_source,
                },
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
            resolved_benchmark_id=resolved.resolved_benchmark_id,
            resolved_benchmark_return_source=resolved.resolved_benchmark_return_source,
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
    benchmark_id: str | None = None,
    benchmark_return_source: str | None = None,
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
    if benchmark_id is not None:
        requested_window["benchmark_id"] = benchmark_id
    if benchmark_return_source is not None:
        requested_window["benchmark_return_source"] = benchmark_return_source
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
    description=(
        "Returns the completed response for an attribution request that was previously accepted "
        "for asynchronous execution, or returns the accepted envelope while the calculation is "
        "still pending. Use this route with result_path from the 202 response."
    ),
    responses={
        202: {
            "model": AttributionAcceptedResponse,
            "description": "Attribution execution is still pending or running.",
        },
        404: {
            "model": ErrorDetailResponse,
            "description": "No async attribution execution exists for the supplied calculation id.",
            "content": {
                "application/json": {
                    "example": {"detail": "Async attribution result not found for the given calculation_id."}
                }
            },
        },
        409: {
            "model": ErrorDetailResponse,
            "description": "The async attribution execution failed and no completed result is available.",
            "content": {"application/json": {"example": {"detail": "Async attribution execution failed."}}},
        },
    },
)
async def get_attribution_result(calculation_id: UUID) -> AttributionResponse | JSONResponse:
    return resolve_async_result(
        calculation_id=calculation_id,
        response_model=AttributionResponse,
        accepted_response_factory=_accepted_attribution_response,
        not_found_detail="Async attribution result not found for the given calculation_id.",
        failed_detail="Async attribution execution failed.",
    )
