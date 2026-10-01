from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.http_status import HTTP_422_UNPROCESSABLE
from app.models.composites import (
    CompositeErrorResponse,
    CompositeInspectionRequest,
    CompositeInspectionResponse,
    CompositeMemberContributionResponse,
    CompositePeriodResultResponse,
    CompositeTWRRequest,
    CompositeTWRResponse,
)
from app.models.platform_surfaces import ErrorDetailResponse
from app.services.composite_calculation_service import (
    CompositeDefinitionNotFoundError,
    calculate_composite_twr_from_persisted_facts,
)
from app.services.composite_inspection_service import inspect_composite_twr_from_persisted_facts
from app.services.composite_metadata_store import CompositeMemberReturnFactSelectionError
from app.services.core_tenant_authority import (
    COMPOSITE_TENANT_AUTHORITY_REQUIRED_DETAIL,
    MALFORMED_TENANT_AUTHORITY_DETAIL,
    MAX_TENANT_ID_LENGTH,
    TENANT_HEADER,
    admitted_tenant_authority_from_header_values,
    require_composite_tenant_authority,
)

router = APIRouter(tags=["Performance"])


def _required_composite_tenant(request: Request) -> str:
    authority = admitted_tenant_authority_from_header_values(request.headers.getlist(TENANT_HEADER))
    return require_composite_tenant_authority(authority).tenant_id


COMPOSITE_TENANT_OPENAPI_EXTRA = {
    "parameters": [
        {
            "name": TENANT_HEADER,
            "in": "header",
            "required": True,
            "schema": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_TENANT_ID_LENGTH,
                "example": "private-bank-sg",
            },
            "description": (
                "Required admitted tenant authority for Performance-owned composite state. "
                "Surrounding whitespace is trimmed; the service never mints or defaults this value."
            ),
        }
    ]
}


COMPOSITE_TENANT_AUTHORITY_RESPONSES = {
    400: {
        "model": ErrorDetailResponse,
        "description": (
            "X-Tenant-Id was duplicated or its normalized value exceeds the supported 128-character authority bound."
        ),
        "content": {
            "application/json": {
                "example": {
                    "detail": MALFORMED_TENANT_AUTHORITY_DETAIL,
                    "error_code": "TENANT_AUTHORITY_MALFORMED",
                    "message": MALFORMED_TENANT_AUTHORITY_DETAIL,
                    "retryable": False,
                }
            }
        },
    },
    401: {
        "model": ErrorDetailResponse,
        "description": "The composite request did not carry the required X-Tenant-Id authority.",
        "content": {
            "application/json": {
                "example": {
                    "detail": COMPOSITE_TENANT_AUTHORITY_REQUIRED_DETAIL,
                    "error_code": "TENANT_AUTHORITY_REQUIRED",
                    "message": COMPOSITE_TENANT_AUTHORITY_REQUIRED_DETAIL,
                    "retryable": False,
                }
            }
        },
    },
}


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
FACT_SELECTION_CONFLICT_RESPONSE = {
    "model": CompositeErrorResponse,
    "description": "The explicit fact sequence is absent or the latest sequence is incompletely published.",
    "content": {
        "application/json": {
            "example": {
                "detail": {
                    "code": "COMPOSITE_FACT_SELECTION_INCOMPLETE",
                    "message": "The requested composite fact selection is unavailable or incomplete.",
                }
            }
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
        restatement_sequence=item.restatement_sequence,
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
        restatement_sequence=item.restatement_sequence,
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
        **COMPOSITE_TENANT_AUTHORITY_RESPONSES,
        409: FACT_SELECTION_CONFLICT_RESPONSE,
        404: COMPOSITE_NOT_FOUND_RESPONSE,
        422: NO_MEMBER_RETURN_FACTS_RESPONSE,
    },
    openapi_extra=COMPOSITE_TENANT_OPENAPI_EXTRA,
)
def calculate_composite_twr(
    request: CompositeTWRRequest,
    tenant_id: Annotated[str, Depends(_required_composite_tenant)],
) -> CompositeTWRResponse:
    try:
        result = calculate_composite_twr_from_persisted_facts(
            tenant_id=tenant_id,
            composite_id=request.composite_id,
            period_start=request.period_start,
            period_end=request.period_end,
            return_view=request.return_view,
            reporting_currency=request.reporting_currency,
            restatement_sequence=request.restatement_sequence,
        )
    except CompositeDefinitionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COMPOSITE_NOT_FOUND", "message": str(exc)},
        ) from exc
    except CompositeMemberReturnFactSelectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "COMPOSITE_FACT_SELECTION_INCOMPLETE", "message": str(exc)},
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
        **COMPOSITE_TENANT_AUTHORITY_RESPONSES,
        409: FACT_SELECTION_CONFLICT_RESPONSE,
        404: COMPOSITE_NOT_FOUND_RESPONSE,
    },
    openapi_extra=COMPOSITE_TENANT_OPENAPI_EXTRA,
)
def inspect_composite_twr(
    request: CompositeInspectionRequest,
    tenant_id: Annotated[str, Depends(_required_composite_tenant)],
) -> CompositeInspectionResponse:
    try:
        return inspect_composite_twr_from_persisted_facts(
            tenant_id=tenant_id,
            inspection_id=request.inspection_id,
            composite_id=request.composite_id,
            period_start=request.period_start,
            period_end=request.period_end,
            return_view=request.return_view,
            reporting_currency=request.reporting_currency,
            restatement_sequence=request.restatement_sequence,
        )
    except CompositeDefinitionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COMPOSITE_NOT_FOUND", "message": str(exc)},
        ) from exc
    except CompositeMemberReturnFactSelectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "COMPOSITE_FACT_SELECTION_INCOMPLETE", "message": str(exc)},
        ) from exc
