from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.api.dependencies.composite_annual_dispersion import (
    annual_comparison_openapi_examples,
    annual_dispersion_openapi_examples,
    get_annual_dispersion_receipt_reader,
)
from app.api.dependencies.composite_attribution import (
    attribution_openapi_examples,
    missing_composite_analysis_example,
    named_attribution_examples,
)
from app.api.dependencies.composite_fee_drag import fee_drag_openapi_examples
from app.api.dependencies.composite_linked_contribution import linked_contribution_openapi_examples
from app.api.dependencies.composite_pooled_mwr import require_pooled_principal
from app.api.http_response_adapter import to_fastapi_response
from app.api.http_status import HTTP_422_UNPROCESSABLE
from app.composite_principal_admission import VERIFIED_SURFACE_STATE_KEY, trusted_request_principal
from app.models.composite_analytics import CompositeAnalyticsRequest, CompositeAnalyticsResponse
from app.models.composite_annual_comparison import CompositeAnnualComparisonRequest, CompositeAnnualComparisonResponse
from app.models.composite_annual_dispersion import CompositeAnnualDispersionResponse
from app.models.composite_attribution import (
    CompositeAttributionAcceptedResponse,
    CompositeAttributionRequest,
    CompositeAttributionResponse,
)
from app.models.composite_fee_drag import CompositeFeeDragRequest, CompositeFeeDragResponse
from app.models.composite_linked_contribution import (
    CompositeLinkedContributionRequest,
    CompositeLinkedContributionResponse,
)
from app.models.composite_pooled_mwr import (
    CompositePooledMWRAcceptedResponse,
    CompositePooledMWRRequest,
    CompositePooledMWRResponse,
)
from app.models.composite_result_candidates import (
    CompositeResultCandidateErrorResponse,
    CompositeResultCandidateResponse,
    CompositeResultCaptureRequest,
)
from app.models.composites import (
    CompositeErrorResponse,
    CompositeInspectionRequest,
    CompositeInspectionResponse,
    CompositeMemberContributionResponse,
    CompositePeriodResultResponse,
    CompositeTWRRequest,
    CompositeTWRResponse,
    CompositeTWRSelectionManifest,
)
from app.models.platform_surfaces import ErrorDetailResponse
from app.ports.composite_annual_dispersion import AnnualDispersionReceiptReader
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_COMPOSITE_ATTRIBUTION
from app.services.calculation_engine_version import calculation_engine_version
from app.services.composite_annual_dispersion.application import calculate_annual_member_dispersion
from app.services.composite_annual_dispersion.comparison import compare_annual_member_dispersion
from app.services.composite_attribution.application import read_attribution_result, submit_attribution
from app.services.composite_calculation_service import (
    CompositeDefinitionNotFoundError,
    calculate_composite_twr_from_materializations,
    calculate_composite_twr_from_persisted_facts,
)
from app.services.composite_fee_drag.application import calculate_model_fee_drag
from app.services.composite_inspection_service import inspect_composite_twr_from_persisted_facts
from app.services.composite_linked_contribution.application import calculate_linked_member_contribution
from app.services.composite_metadata_store import CompositeMemberReturnFactSelectionError
from app.services.composite_pooled_mwr.application import read_pooled_mwr_result, submit_pooled_mwr
from app.services.composite_result_candidate_admission import (
    admit_candidate_calculation,
    read_result_candidate,
    require_verified_candidate_principal,
)
from app.services.compute_job_store import compute_job_store
from app.services.core_tenant_authority import (
    COMPOSITE_TENANT_AUTHORITY_REQUIRED_DETAIL,
    MALFORMED_TENANT_AUTHORITY_DETAIL,
    MAX_TENANT_ID_LENGTH,
    TENANT_HEADER,
    admitted_tenant_authority_from_header_values,
    require_composite_tenant_authority,
)
from app.services.reproducibility_service import generate_value_fingerprint

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
    "description": "The request window is invalid, facts are unavailable, or authoritative ending assets are unavailable.",
    "content": {
        "application/json": {
            "schema": {
                "oneOf": [
                    {"$ref": "#/components/schemas/CompositeErrorResponse"},
                    {"$ref": "#/components/schemas/HTTPValidationError"},
                ]
            },
            "examples": {
                "ending_assets_unavailable": {
                    "summary": "Published v2 facts have no selected ending-asset authority.",
                    "value": {
                        "detail": {
                            "code": "COMPOSITE_ENDING_ASSETS_UNAVAILABLE",
                            "message": "This composite calculation includes asset reporting and requires authoritative ending assets.",
                        }
                    },
                },
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
    "description": (
        "The explicit fact sequence is absent or the latest sequence is incompletely published. "
        "An explicit retained window vector with a missing or unavailable required period refuses "
        "with REQUIRED_PERIOD_UNAVAILABLE and no financial result."
    ),
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
        source_authority_identity=item.source_authority_identity,
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
        "returns and does not perform hidden request-time portfolio TWR fan-out. Optional materialization_ids "
        "selects 1–120 chronological immutable windows for calculated historical replay, with exact shared "
        "method authority and complete interval coverage. The new interactive limit supports ten years of "
        "monthly windows; larger vectors refuse validation without truncation. This selection is mutually "
        "exclusive with restatement_sequence. A successful explicit replay returns a selection manifest "
        "and calculation fingerprint; it does not confer official approval or durable freeze authority."
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
        windows = None
        if request.materialization_ids is not None:
            result, windows = calculate_composite_twr_from_materializations(tenant_id=tenant_id, request=request)
        else:
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

    response = CompositeTWRResponse(
        calculation_id=request.calculation_id,
        composite_id=result.composite_id,
        status=result.status,
        period_start=request.period_start,
        period_end=request.period_end,
        cumulative_return=result.cumulative_return,
        reason_codes=result.reason_codes,
        periods=[_period_response(period) for period in result.period_results],
    )
    if windows is not None:
        version = calculation_engine_version()
        fingerprint = generate_value_fingerprint(
            {
                "tenant_id": tenant_id,
                "request": request.model_dump(mode="json"),
                "windows": [window.model_dump(mode="json") for window in windows],
                "result": response.model_dump(mode="json"),
            },
            version,
        )[0]
        response.selection_manifest = CompositeTWRSelectionManifest(
            windows=windows, engine_version=version, calculation_fingerprint=fingerprint
        )
    return response


def _verified_candidate_principal(request: Request):
    return require_verified_candidate_principal(trusted_request_principal(request))


def _candidate_error_response(description, code, message, denial_class=None):
    detail = {"code": code, "message": message, "denial_class": denial_class} if denial_class else message
    return {
        "model": CompositeResultCandidateErrorResponse,
        "description": description,
        "content": {
            "application/json": {
                "example": {
                    "detail": detail,
                    "error_code": code,
                    "message": message,
                    "source": "lotus-performance",
                    "retryable": False,
                }
            }
        },
    }


@router.post(
    "/composites/result-candidates",
    response_model=CompositeResultCandidateResponse,
    summary="Capture an immutable calculated composite result candidate",
    description=(
        "Calculates from an explicit complete retained vector, then atomically captures the original response "
        "in the existing analytics result store and an immutable descriptor in the same owning database. "
        "Requires a deployment-verified Ed25519 bearer principal, current tenant membership and operations.runtime.manage "
        "grant with every retained universe member in scope. Asserted actor, tenant, role and capability headers supply no authority. "
        "Unconfigured trust, missing release provenance and cross-database custody refuse. Ordinary calculation does not capture. "
        "Same-content retries preserve the first response and calculation identity. This candidate is calculated analysis; "
        "it does not approve financial source makers, select an official result, freeze a period or attest an institution."
    ),
    responses={
        401: _candidate_error_response(
            "Credential missing or unverified.",
            "PRINCIPAL_ADMISSION_DENIED",
            "Principal admission refused.",
            "missing_credential",
        ),
        403: _candidate_error_response(
            "Current trusted grants or portfolio scope refused.",
            "PRINCIPAL_ADMISSION_DENIED",
            "Principal admission refused.",
            "capability_not_granted",
        ),
        409: _candidate_error_response(
            "Original identity conflict or incomplete retained evidence.",
            "COMPOSITE_CAPTURE_EVIDENCE_INCOMPLETE",
            "Capture requires a complete READY response.",
        ),
        503: _candidate_error_response(
            "Original result custody or build provenance unavailable.",
            "COMPOSITE_RESULT_CUSTODY_REFUSED",
            "The service encountered an internal error. Use the correlation_id for support.",
        ),
    },
)
def capture_composite_result_candidate(request: CompositeResultCaptureRequest, http_request: Request):
    principal = _verified_candidate_principal(http_request)
    store, results = admit_candidate_calculation(request.calculation, principal)
    response = calculate_composite_twr(request.calculation, principal.tenant_id)
    return store.capture_result_candidate(
        candidate_id=request.candidate_id,
        request=request.calculation,
        response=response,
        principal=principal,
        result_store=results,
    )


@router.get(
    "/composites/result-candidates/{candidate_id}",
    response_model=CompositeResultCandidateResponse,
    summary="Read the original captured composite response",
    description=(
        "Reads the original response, calculation identity and captured build/method provenance without recalculation. "
        "Requires a deployment-verified bearer principal and operations.runtime.read grant in its tenant, with every included "
        "portfolio still in scope. Missing or inconsistent original custody refuses; current engine/build versions never rewrite history."
    ),
    responses={
        401: _candidate_error_response(
            "Credential missing or unverified.",
            "PRINCIPAL_ADMISSION_DENIED",
            "Principal admission refused.",
            "missing_credential",
        ),
        403: _candidate_error_response(
            "Current grants or scope refused.",
            "PRINCIPAL_ADMISSION_DENIED",
            "Principal admission refused.",
            "capability_not_granted",
        ),
        404: _candidate_error_response(
            "Candidate absent in the verified tenant.",
            "COMPOSITE_RESULT_CANDIDATE_NOT_FOUND",
            "Candidate is absent in the verified tenant.",
        ),
        503: _candidate_error_response(
            "Original custody unavailable.",
            "COMPOSITE_RESULT_CUSTODY_REFUSED",
            "The service encountered an internal error. Use the correlation_id for support.",
        ),
    },
)
def get_composite_result_candidate(candidate_id: UUID, http_request: Request):
    principal = _verified_candidate_principal(http_request)
    return read_result_candidate(candidate_id, principal)


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


ANNUAL_DISPERSION_OPENAPI_EXAMPLES = annual_dispersion_openapi_examples()
LINKED_CONTRIBUTION_OPENAPI_EXAMPLES = linked_contribution_openapi_examples()
FEE_DRAG_OPENAPI_EXAMPLES = fee_drag_openapi_examples()
ATTRIBUTION_OPENAPI_EXAMPLES = attribution_openapi_examples()


@router.post(
    "/composites/analytics",
    response_model=CompositeAnalyticsResponse,
    summary="Evaluate named Composite analytics from exact retained evidence",
    description=(
        "One bounded composite analytics operation with explicit metric and method selection. "
        "ANNUAL_MEMBER_DISPERSION uses twelve exact COMPLETE calendar-month receipts. "
        "LINKED_MEMBER_CONTRIBUTION with CARINO:v1 uses 1–120 chronological COMPLETE receipts and original "
        "source economics. POOLED_MONEY_WEIGHTED_RETURN with XIRR:v1 registers an asynchronous ACT/365 "
        "pooled monetary calculation using qualified source ports and verified principal/member scope. "
        "Original monetary inputs and results are retained immutably; corrections use new calculation IDs. "
        "Member IRRs are never averaged. Missing supplier authority refuses; controlled examples remain synthetic. "
        "SINGLE_PERIOD_BRINSON_FACHLER registers an asynchronous arithmetic allocation, selection and interaction "
        "analysis against one retained READY Composite original. Complete source-owned group economics and separate "
        "financial-purpose authority are required; source and authority defaults are unavailable. "
        "MODEL_FEE_DRAG compares original gross and model-net returns from the same complete retained model-fee "
        "receipt vector. Period and independently linked horizon differences are decimal return differences, not cash fees. "
        "The linked metric uses "
        "Decimal beginning-asset economics, never quantized public weights. Decimal-return units; "
        "multiply by 100 for percentage points or 10000 for basis points. Continuous zero/near-zero "
        "factors are supported; nonpositive growth refuses. No residual allocation or composite-only override. "
        "Consumes historical Manage membership and verified member returns without source fan-out. "
        "Financial computability, small-population reporting applicability and source qualification are separate. "
        "Results are non-official calculated analysis; no external-return import, official approval or risk engine is implied. "
        "Exact replay uses the same retained receipt vector beyond ordinary execution expiry. "
        "Documentation examples are synthetic; a real call requires its tenant's retained receipts."
    ),
    responses={
        202: {
            "model": CompositePooledMWRAcceptedResponse | CompositeAttributionAcceptedResponse,
            "description": "Pooled XIRR or single-period BF accepted for the existing compute worker; follow result_path.",
            "content": {
                "application/json": {"examples": named_attribution_examples(ATTRIBUTION_OPENAPI_EXAMPLES, "accepted")}
            },
        },
        200: {
            "description": "Named annual dispersion, linked member contribution or same-population model fee drag.",
            "content": {
                "application/json": {
                    "examples": {
                        "annual_member_dispersion": {"value": ANNUAL_DISPERSION_OPENAPI_EXAMPLES["response"]},
                        "linked_member_contribution": {"value": LINKED_CONTRIBUTION_OPENAPI_EXAMPLES["response"]},
                        "model_fee_drag": {"value": FEE_DRAG_OPENAPI_EXAMPLES["response"]},
                    }
                }
            },
        },
        **COMPOSITE_TENANT_AUTHORITY_RESPONSES,
        404: {
            "model": ErrorDetailResponse,
            "description": "A retained receipt is absent in the admitted tenant.",
            "content": {"application/json": {"example": ANNUAL_DISPERSION_OPENAPI_EXAMPLES["errors"]["not_found"]}},
        },
        409: {
            "model": ErrorDetailResponse,
            "description": "A selected monthly receipt or its immutable publication is incomplete.",
            "content": {"application/json": {"example": ANNUAL_DISPERSION_OPENAPI_EXAMPLES["errors"]["incomplete"]}},
        },
        422: {
            "model": ErrorDetailResponse,
            "description": "Invalid metric request or incompatible annual source, currency, fee, policy or numerical domain.",
            "content": {
                "application/json": {
                    "examples": {
                        "requestValidation": {
                            "value": ANNUAL_DISPERSION_OPENAPI_EXAMPLES["errors"]["request_validation"]
                        },
                        "domainAdmission": {"value": ANNUAL_DISPERSION_OPENAPI_EXAMPLES["errors"]["domain_admission"]},
                        "bf_strict_precision": {"value": ATTRIBUTION_OPENAPI_EXAMPLES["errors"]["strict_precision"]},
                    }
                }
            },
        },
        503: {
            "model": ErrorDetailResponse,
            "description": "Source authority is unavailable or retained materialization evidence failed validation.",
            "content": {
                "application/json": {
                    "examples": {
                        "retained_evidence": {
                            "value": ANNUAL_DISPERSION_OPENAPI_EXAMPLES["errors"]["retained_evidence"]
                        },
                        "bf_source_unavailable": {
                            "value": ATTRIBUTION_OPENAPI_EXAMPLES["errors"]["source_unavailable"]
                        },
                    },
                }
            },
        },
    },
    openapi_extra={
        **COMPOSITE_TENANT_OPENAPI_EXTRA,
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "annual_member_dispersion": {"value": ANNUAL_DISPERSION_OPENAPI_EXAMPLES["request"]},
                        "linked_member_contribution": {"value": LINKED_CONTRIBUTION_OPENAPI_EXAMPLES["request"]},
                        "model_fee_drag": {"value": FEE_DRAG_OPENAPI_EXAMPLES["request"]},
                        **named_attribution_examples(ATTRIBUTION_OPENAPI_EXAMPLES, "request", "correction_request"),
                    }
                }
            }
        },
    },
)
def evaluate_composite_analytics(
    request: CompositeAnalyticsRequest,
    http_request: Request,
    tenant_id: Annotated[str, Depends(_required_composite_tenant)],
    reader: Annotated[AnnualDispersionReceiptReader, Depends(get_annual_dispersion_receipt_reader)],
) -> CompositeAnnualDispersionResponse | CompositeLinkedContributionResponse | CompositeFeeDragResponse | JSONResponse:
    if isinstance(request, CompositeAttributionRequest):
        principal = require_pooled_principal(http_request, tenant_id=tenant_id)
        return to_fastapi_response(submit_attribution(request, principal=principal))
    if isinstance(request, CompositePooledMWRRequest):
        principal = require_pooled_principal(http_request, tenant_id=tenant_id)
        return to_fastapi_response(submit_pooled_mwr(request, principal=principal))
    if isinstance(request, CompositeFeeDragRequest):
        return calculate_model_fee_drag(request, tenant_id=tenant_id)
    if isinstance(request, CompositeLinkedContributionRequest):
        return calculate_linked_member_contribution(request, tenant_id=tenant_id)
    return calculate_annual_member_dispersion(request, tenant_id=tenant_id, reader=reader)


@router.get(
    "/composites/analytics/results/{calculation_id}",
    response_model=CompositePooledMWRResponse | CompositeAttributionResponse,
    summary="Read a retained Composite calculated analysis original",
    description=(
        "Read the exact retained pooled XIRR or single-period BF result in the verified tenant and member scope. "
        "Pending work returns 202. BF original replay returns the same source revisions, immutable effects and "
        "explicit official-selection nulls without new source reads or approval. Corrections have new calculation IDs. "
        "Named BF examples use controlled synthetic observations and non-certifying purpose evidence; "
        "they grant no institutional source, official selection or downstream publication approval."
    ),
    responses={
        200: {
            "description": "Immutable calculated analysis; original and corrected BF observations remain separately replayable.",
            "content": {
                "application/json": {
                    "examples": named_attribution_examples(
                        ATTRIBUTION_OPENAPI_EXAMPLES, "original_ready", "original_replay", "corrected_ready"
                    )
                }
            },
        },
        202: {
            "model": CompositePooledMWRAcceptedResponse | CompositeAttributionAcceptedResponse,
            "description": "The registered calculation is pending or running; follow result_path.",
            "content": {
                "application/json": {"examples": named_attribution_examples(ATTRIBUTION_OPENAPI_EXAMPLES, "pending")}
            },
        },
        **COMPOSITE_TENANT_AUTHORITY_RESPONSES,
        404: {
            "model": ErrorDetailResponse,
            "description": "The calculation is absent in the verified tenant; the shared route uses its existing pooled reader.",
            "content": {"application/json": {"example": missing_composite_analysis_example()}},
        },
        409: {
            "model": ErrorDetailResponse,
            "description": "The source universe or retained original custody is inconsistent or incomplete.",
            "content": {
                "application/json": {
                    "examples": {
                        "bf_incomplete_groups": {"value": ATTRIBUTION_OPENAPI_EXAMPLES["errors"]["incomplete_groups"]}
                    }
                }
            },
        },
        503: {
            "model": ErrorDetailResponse,
            "description": "Historical source or independent BF-purpose authority is unavailable; no financial result is published.",
            "content": {
                "application/json": {
                    "examples": {
                        "bf_source_unavailable": {
                            "value": ATTRIBUTION_OPENAPI_EXAMPLES["errors"]["source_unavailable"]
                        },
                        "bf_purpose_unavailable": {
                            "value": ATTRIBUTION_OPENAPI_EXAMPLES["errors"]["purpose_unavailable"]
                        },
                    }
                }
            },
        },
    },
    openapi_extra=COMPOSITE_TENANT_OPENAPI_EXTRA,
)
def get_pooled_composite_analytics_result(
    calculation_id: UUID,
    http_request: Request,
    tenant_id: Annotated[str, Depends(_required_composite_tenant)],
):
    principal = require_pooled_principal(http_request, tenant_id=tenant_id)
    job = compute_job_store.get_job_for_tenant(calculation_id, tenant_id=tenant_id)
    if job is not None and job.analytics_type == ANALYTICS_WORKFLOW_COMPOSITE_ATTRIBUTION:
        setattr(http_request.state, VERIFIED_SURFACE_STATE_KEY, "composite_attribution")
        return to_fastapi_response(read_attribution_result(calculation_id, principal=principal))
    return to_fastapi_response(read_pooled_mwr_result(calculation_id, principal=principal))


ANNUAL_COMPARISON_OPENAPI_EXAMPLES = annual_comparison_openapi_examples()


@router.post(
    "/composites/analytics/comparison",
    response_model=CompositeAnnualComparisonResponse,
    summary="Compare two explicit pinned annual dispersion results",
    description=(
        "Independently admits both retained annual receipt vectors on the same composite, year, fee, currency, "
        "method, definition and policy basis. Preserves both full v1 results and compares their quantized outputs. "
        "Member additions/removals describe full-year identity sets, not causal attribution. Neither side is "
        "automatically original, latest, approved, frozen or official. Synthetic examples require retained tenant evidence."
    ),
    responses={
        200: {
            "description": "Available output difference or null with side-specific unavailability reasons.",
            "content": {"application/json": {"example": ANNUAL_COMPARISON_OPENAPI_EXAMPLES["response"]}},
        },
        **COMPOSITE_TENANT_AUTHORITY_RESPONSES,
        **{
            code: {
                "model": ErrorDetailResponse,
                "description": description,
                "content": {
                    "application/json": {
                        "examples": {
                            name: {"value": ANNUAL_COMPARISON_OPENAPI_EXAMPLES["errors"][name]} for name in names
                        }
                    }
                },
            }
            for code, description, names in (
                (404, "Either side selects a receipt absent in the admitted tenant.", ("not_found",)),
                (409, "Either selected receipt or publication is incomplete.", ("incomplete",)),
                (
                    422,
                    "Invalid paired request or incompatible admitted evidence or numerical domain.",
                    ("request_validation", "domain_admission", "comparison_basis"),
                ),
                (503, "Retained evidence failed validation; reviewed recovery is required.", ("retained_evidence",)),
            )
        },
    },
    openapi_extra={
        **COMPOSITE_TENANT_OPENAPI_EXTRA,
        "requestBody": {"content": {"application/json": {"example": ANNUAL_COMPARISON_OPENAPI_EXAMPLES["request"]}}},
    },
)
def evaluate_composite_analytics_comparison(
    request: CompositeAnnualComparisonRequest,
    tenant_id: Annotated[str, Depends(_required_composite_tenant)],
    reader: Annotated[AnnualDispersionReceiptReader, Depends(get_annual_dispersion_receipt_reader)],
) -> CompositeAnnualComparisonResponse:
    return compare_annual_member_dispersion(request, tenant_id=tenant_id, reader=reader)
