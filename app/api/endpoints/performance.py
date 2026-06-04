# app/api/endpoints/performance.py
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest
from app.models.attribution_responses import AttributionAcceptedResponse, AttributionResponse
from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest
from app.models.mwr_responses import MoneyWeightedReturnResponse
from app.models.platform_surfaces import ErrorDetailResponse
from app.models.responses import PerformanceResponse, TWRAcceptedResponse
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.models.workspace_summary_responses import WorkspaceSummaryAcceptedResponse, WorkspaceSummaryResponse
from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)
from app.services.async_result_service import resolve_async_result
from app.services.attribution_calculation_workflow_service import (
    accepted_attribution_response as _accepted_attribution_response,
)
from app.services.attribution_calculation_workflow_service import (
    calculate_attribution_workflow,
)
from app.services.execution_lifecycle_service import (
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from app.services.mwr_calculation_service import calculate_mwr_response
from app.services.reproducibility_service import generate_request_fingerprint
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)
from app.services.twr_calculation_service import (
    accepted_twr_response as _accepted_twr_response,
)
from app.services.twr_calculation_service import (
    calculate_twr_workflow,
)
from app.services.workspace_summary_service import (
    calculate_workspace_summary,
    workspace_longest_requested_window_days,
)

router = APIRouter(tags=["Performance"])


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
    return workspace_longest_requested_window_days(request)


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
    return await calculate_twr_workflow(request)


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
    return await calculate_mwr_response(request)


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
    return await calculate_attribution_workflow(request)


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
