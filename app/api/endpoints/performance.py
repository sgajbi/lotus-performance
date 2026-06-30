# app/api/endpoints/performance.py
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.async_openapi import async_result_responses, async_submission_responses
from app.api.http_response_adapter import to_fastapi_response
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest
from app.models.attribution_responses import AttributionAcceptedResponse, AttributionResponse
from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest
from app.models.mwr_responses import MoneyWeightedReturnResponse
from app.models.platform_surfaces import ErrorDetailResponse
from app.models.responses import PerformanceResponse, TWRAcceptedResponse
from app.models.twr_requests import TWRAnalyticsRequest
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.models.workspace_summary_responses import WorkspaceSummaryAcceptedResponse, WorkspaceSummaryResponse
from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_ATTRIBUTION,
    ANALYTICS_WORKFLOW_TWR,
    ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
)
from app.services.async_result_service import resolve_async_result
from app.services.attribution_calculation_workflow_service import (
    accepted_attribution_response as _accepted_attribution_response,
)
from app.services.attribution_calculation_workflow_service import (
    calculate_attribution_workflow,
)
from app.services.mwr_calculation_service import calculate_mwr_response
from app.services.twr_calculation_service import (
    accepted_twr_response as _accepted_twr_response,
)
from app.services.twr_calculation_service import (
    calculate_twr_workflow,
)
from app.services.workspace_summary_calculation_workflow_service import (
    accepted_workspace_summary_response as _accepted_workspace_summary_response,
)
from app.services.workspace_summary_calculation_workflow_service import (
    calculate_workspace_summary_workflow,
)

router = APIRouter(tags=["Performance"])


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
    responses=async_submission_responses(
        accepted_model=WorkspaceSummaryAcceptedResponse,
        analytics_name="workspace-summary",
        result_path_template="/performance/workspace-summary/results/{calculation_id}",
    ),
)
def calculate_workspace_summary_endpoint(
    request: WorkspaceSummaryRequest,
) -> WorkspaceSummaryResponse | JSONResponse:
    """Calculates multi-horizon workspace summary analytics in one source-owned response."""
    return to_fastapi_response(calculate_workspace_summary_workflow(request))


@router.get(
    "/workspace-summary/results/{calculation_id}",
    response_model=WorkspaceSummaryResponse | WorkspaceSummaryAcceptedResponse,
    summary="Retrieve async workspace summary result",
    description=(
        "Retrieves the completed workspace-summary response for an async request, or returns the "
        "accepted envelope while execution remains pending."
    ),
    responses=async_result_responses(
        accepted_model=WorkspaceSummaryAcceptedResponse,
        analytics_name="workspace-summary",
        result_path_template="/performance/workspace-summary/results/{calculation_id}",
        not_found_detail="Async workspace summary result not found for the given calculation_id.",
        failed_detail="Async workspace summary execution failed.",
    ),
)
async def get_workspace_summary_result(
    calculation_id: UUID,
    request: Request,
) -> WorkspaceSummaryResponse | JSONResponse:
    return to_fastapi_response(
        resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type=ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
            response_model=WorkspaceSummaryResponse,
            accepted_response_factory=_accepted_workspace_summary_response,
            not_found_detail="Async workspace summary result not found for the given calculation_id.",
            failed_detail="Async workspace summary execution failed.",
            request_headers=request.headers,
        )
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
    responses=async_submission_responses(
        accepted_model=TWRAcceptedResponse,
        analytics_name="TWR",
        result_path_template="/performance/twr/results/{calculation_id}",
    ),
)
async def calculate_twr_endpoint(request: TWRAnalyticsRequest) -> PerformanceResponse | JSONResponse:
    """
    Calculates time-weighted return (TWR) for one or more requested periods
    and provides performance breakdowns by requested frequencies.
    """
    return to_fastapi_response(await calculate_twr_workflow(request))


@router.get(
    "/twr/results/{calculation_id}",
    response_model=PerformanceResponse | TWRAcceptedResponse,
    summary="Retrieve async TWR result",
    description=(
        "Retrieves the result for a TWR request that previously returned 202 Accepted. "
        "Returns the completed PerformanceResponse when execution is complete, or the "
        "accepted envelope while the durable calculation is still pending."
    ),
    responses=async_result_responses(
        accepted_model=TWRAcceptedResponse,
        analytics_name="TWR",
        result_path_template="/performance/twr/results/{calculation_id}",
        not_found_detail="Async TWR result not found for the given calculation_id.",
        failed_detail="Async TWR execution failed.",
    ),
)
async def get_twr_result(calculation_id: UUID, request: Request) -> PerformanceResponse | JSONResponse:
    return to_fastapi_response(
        resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type=ANALYTICS_WORKFLOW_TWR,
            response_model=PerformanceResponse,
            accepted_response_factory=_accepted_twr_response,
            not_found_detail="Async TWR result not found for the given calculation_id.",
            failed_detail="Async TWR execution failed.",
            request_headers=request.headers,
        )
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
    return to_fastapi_response(await calculate_attribution_workflow(request))


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
async def get_attribution_result(calculation_id: UUID, request: Request) -> AttributionResponse | JSONResponse:
    return to_fastapi_response(
        resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type=ANALYTICS_WORKFLOW_ATTRIBUTION,
            response_model=AttributionResponse,
            accepted_response_factory=_accepted_attribution_response,
            not_found_detail="Async attribution result not found for the given calculation_id.",
            failed_detail="Async attribution execution failed.",
            request_headers=request.headers,
        )
    )
