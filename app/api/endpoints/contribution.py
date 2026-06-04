# app/api/endpoints/contribution.py
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.models.contribution_analytics_requests import ContributionAnalyticsRequest
from app.models.contribution_responses import (
    ContributionAcceptedResponse,
    ContributionResponse,
)
from app.services.analytics_numeric import numeric_value
from app.services.async_result_service import resolve_async_result
from app.services.contribution_calculation_workflow_service import (
    accepted_contribution_response,
    calculate_contribution_workflow,
)

router = APIRouter()


def _as_numeric(value: object, default=0):
    return numeric_value(value, default=default)


@router.post(
    "/contribution",
    response_model=ContributionResponse | ContributionAcceptedResponse,
    summary="Calculate Position Contribution",
    description=(
        "Calculates position-level and optional hierarchy-level contribution to portfolio return. "
        "Use this endpoint when a client needs to explain which positions, sectors, asset classes, "
        "countries, or other supported dimensions drove a portfolio return over one or more resolved "
        "periods. Stateless requests provide valuation points directly. Stateful requests source "
        "canonical portfolio and position analytics inputs from lotus-core query-control-plane, then "
        "normalize them into the same calculation engine. Large requests may return 202 with poll and "
        "result paths; retrieve the completed result from `/performance/contribution/results/{calculation_id}`."
    ),
)
async def calculate_contribution_endpoint(
    request: ContributionAnalyticsRequest,
) -> ContributionResponse | JSONResponse:
    return await calculate_contribution_workflow(request)


@router.get(
    "/contribution/results/{calculation_id}",
    response_model=ContributionResponse | ContributionAcceptedResponse,
    summary="Retrieve async contribution result",
    description=(
        "Retrieves the completed result for an asynchronous contribution calculation. Use the "
        "`result_path` returned by `POST /performance/contribution` after polling the execution status. "
        "The endpoint returns 202 while the calculation is still pending, 200 when complete, 404 when "
        "the calculation_id is unknown, and 409 when the asynchronous calculation failed."
    ),
)
async def get_contribution_result(calculation_id: UUID) -> ContributionResponse | JSONResponse:
    return resolve_async_result(
        calculation_id=calculation_id,
        response_model=ContributionResponse,
        accepted_response_factory=accepted_contribution_response,
        not_found_detail="Async contribution result not found for the given calculation_id.",
        failed_detail="Async contribution execution failed.",
    )
