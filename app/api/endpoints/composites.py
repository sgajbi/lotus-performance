from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.models.composites import (
    CompositeErrorResponse,
    CompositeInspectionRequest,
    CompositeInspectionResponse,
    CompositeMemberContributionResponse,
    CompositePeriodResultResponse,
    CompositeTWRRequest,
    CompositeTWRResponse,
)
from app.services.composite_calculation_service import (
    CompositeDefinitionNotFoundError,
    calculate_composite_twr_from_persisted_facts,
)
from app.services.composite_inspection_service import inspect_composite_twr_from_persisted_facts
from core.errors import HTTP_422_UNPROCESSABLE

router = APIRouter(tags=["Performance"])


COMPOSITE_NOT_FOUND_RESPONSE = {
    "model": CompositeErrorResponse,
    "description": "Composite definition was not found in the durable composite metadata store.",
    "content": {
        "application/json": {
            "example": {
                "detail": {
                    "code": "COMPOSITE_NOT_FOUND",
                    "message": "Composite definition 'MISSING_COMPOSITE' was not found.",
                }
            }
        }
    },
}
NO_MEMBER_RETURN_FACTS_RESPONSE = {
    "description": "The request window is invalid or no persisted member-return facts can support it.",
    "content": {
        "application/json": {
            "schema": {
                "oneOf": [
                    {"$ref": "#/components/schemas/CompositeErrorResponse"},
                    {"$ref": "#/components/schemas/HTTPValidationError"},
                ]
            },
            "examples": {
                "no_persisted_member_return_facts": {
                    "summary": "No persisted member-return facts exist for the requested window.",
                    "value": {
                        "detail": {
                            "code": "NO_MEMBER_RETURN_FACTS",
                            "message": "No persisted member-return facts exist for the requested composite window.",
                        }
                    },
                },
                "invalid_window": {
                    "summary": "The request end date is before the request start date.",
                    "value": {
                        "detail": [
                            {
                                "type": "value_error",
                                "loc": ["body"],
                                "msg": "Value error, period_end cannot be before period_start",
                                "input": {
                                    "composite_id": "PB_GLOBAL_BALANCED_USD",
                                    "period_start": "2026-02-01",
                                    "period_end": "2026-01-31",
                                },
                            }
                        ]
                    },
                },
            },
        }
    },
}


def _member_contribution_response(item) -> CompositeMemberContributionResponse:
    return CompositeMemberContributionResponse(
        portfolio_id=item.portfolio_id,
        period_start=item.period_start,
        period_end=item.period_end,
        return_value=item.return_value,
        beginning_market_value=item.beginning_market_value,
        beginning_asset_weight=item.weight,
        contribution=item.contribution,
        source_snapshot_id=item.source_snapshot_id,
        source_fingerprint=item.source_fingerprint,
        restatement_version=item.restatement_version,
        calculation_id=item.calculation_id,
    )


def _period_response(item) -> CompositePeriodResultResponse:
    return CompositePeriodResultResponse(
        period_start=item.period_start,
        period_end=item.period_end,
        status=item.status,
        return_value=item.return_value,
        cumulative_return=item.cumulative_return,
        beginning_market_value=item.beginning_market_value,
        ending_market_value=item.ending_market_value,
        member_count=item.member_count,
        excluded_member_count=item.excluded_member_count,
        dispersion_equal_weight=item.dispersion_equal_weight,
        return_view=item.return_view,
        reporting_currency=item.reporting_currency,
        source_fingerprints=item.source_fingerprints,
        restatement_versions=item.restatement_versions,
        reason_codes=item.reason_codes,
        member_contributions=[
            _member_contribution_response(contribution) for contribution in item.member_contributions
        ],
    )


@router.post(
    "/composites/twr",
    response_model=CompositeTWRResponse,
    summary="Calculate composite time-weighted return from persisted member-return facts",
    description=(
        "Calculates private-banking composite TWR from persisted member-return facts already owned by "
        "lotus-performance. Use this endpoint after composite definitions, effective-dated membership, "
        "and member-return facts have been materialized. The endpoint does not accept ad hoc member "
        "returns and does not perform hidden request-time portfolio TWR fan-out."
    ),
    responses={
        200: {"description": "Composite TWR calculated from persisted member-return facts."},
        404: COMPOSITE_NOT_FOUND_RESPONSE,
        422: NO_MEMBER_RETURN_FACTS_RESPONSE,
    },
)
def calculate_composite_twr(request: CompositeTWRRequest) -> CompositeTWRResponse:
    try:
        result = calculate_composite_twr_from_persisted_facts(
            composite_id=request.composite_id,
            period_start=request.period_start,
            period_end=request.period_end,
        )
    except CompositeDefinitionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COMPOSITE_NOT_FOUND", "message": str(exc)},
        ) from exc

    if not result.period_results:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail={
                "code": "NO_MEMBER_RETURN_FACTS",
                "message": "No persisted member-return facts exist for the requested composite window.",
            },
        )

    return CompositeTWRResponse(
        calculation_id=request.calculation_id,
        composite_id=result.composite_id,
        status=result.status,
        period_start=request.period_start,
        period_end=request.period_end,
        cumulative_return=result.cumulative_return,
        reason_codes=result.reason_codes,
        periods=[_period_response(period) for period in result.period_results],
    )


@router.post(
    "/composites/inspect",
    response_model=CompositeInspectionResponse,
    summary="Inspect composite TWR persisted facts and evidence artifacts",
    description=(
        "Runs support-safe composite inspection over persisted member-return facts. Use this endpoint "
        "when operations, audit, or implementation proof needs member inputs, period weights, composite "
        "returns, lineage manifest, and a support brief without recalculating portfolio-level TWR on the fly."
    ),
    responses={
        200: {"description": "Composite inspection completed over persisted facts."},
        404: COMPOSITE_NOT_FOUND_RESPONSE,
    },
)
def inspect_composite_twr(request: CompositeInspectionRequest) -> CompositeInspectionResponse:
    try:
        return inspect_composite_twr_from_persisted_facts(
            inspection_id=request.inspection_id,
            composite_id=request.composite_id,
            period_start=request.period_start,
            period_end=request.period_end,
        )
    except CompositeDefinitionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COMPOSITE_NOT_FOUND", "message": str(exc)},
        ) from exc
