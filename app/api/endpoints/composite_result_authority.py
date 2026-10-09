"""Nonfinancial captured-original authority commands and exact retained reads."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from app.api.dependencies.composite_result_authority import authority_application, authority_principal
from app.models.composite_result_authority import (
    AuthorityApplyRequest,
    AuthorityApprovalRequest,
    AuthorityApprovalResponse,
    AuthorityDecisionResponse,
    AuthorityProposalRequest,
    AuthorityProposalResponse,
    AuthorityReadResponse,
)
from app.models.composite_result_candidates import CompositeResultCandidateErrorResponse
from app.services.composite_result_authority.application import CompositeAuthorityApplication

Application = Annotated[CompositeAuthorityApplication, Depends(authority_application)]
Principal = Annotated[object, Depends(authority_principal)]
ERRORS = {
    status: {
        "model": CompositeResultCandidateErrorResponse,
        "description": description,
        "content": {
            "application/json": {
                "example": {
                    "detail": description,
                    "error_code": code,
                    "message": description,
                    "source": "lotus-performance",
                    "retryable": False,
                }
            }
        },
    }
    for status, (code, description) in {
        401: ("PRINCIPAL_ADMISSION_DENIED", "Verified credential missing or refused."),
        403: ("COMPOSITE_FINANCIAL_ACTION_DENIED", "Financial action is refused."),
        404: ("COMPOSITE_AUTHORITY_NOT_FOUND", "Authority resource absent in the verified tenant."),
        409: ("COMPOSITE_AUTHORITY_CONFLICT", "Revision, idempotency, dependency, freeze or atomic bundle conflict."),
        422: ("COMPOSITE_AUTHORITY_UNSUPPORTED", "Unsupported authority selector or invalid command."),
        503: ("COMPOSITE_FINANCIAL_AUTHORITY_UNAVAILABLE", "Financial-result authority is unavailable."),
    }.items()
}
router = APIRouter(prefix="/composites/result-authorities", tags=["Performance"], responses=ERRORS)


@router.post(
    "/proposals",
    response_model=AuthorityProposalResponse,
    summary="Propose an exact captured composite authority action",
    description="Retains complete candidate vectors, expected revisions and a digest-bound local impact preview. "
    "No selection changes. Caller-supplied tenant, role and portfolio assertions are forbidden. "
    "Report versions, recipients and institutional materiality remain explicitly unavailable.",
)
def propose_authority(request: AuthorityProposalRequest, application: Application, principal: Principal):
    return application.propose(principal, request)


@router.post(
    "/proposals/{proposal_id}/approvals",
    response_model=AuthorityApprovalResponse,
    summary="Approve an exact composite authority proposal independently",
    description="Requires distinct canonical human checker and purpose-specific signed financial evidence. "
    "The default verifier refuses with 503 before approval writes. Configured synthetic conformance remains "
    "SYNTHETIC_NON_CERTIFYING and cannot activate an institution. Approval alone never changes selection.",
)
def approve_authority(
    proposal_id: UUID, request: AuthorityApprovalRequest, application: Application, principal: Principal
):
    return application.approve(principal, proposal_id, request)


@router.post(
    "/proposals/{proposal_id}/apply",
    response_model=AuthorityDecisionResponse,
    summary="Apply an approved composite authority action atomically",
    description="Revalidates financial purpose before the owning transaction, then fences exact revision CAS, "
    "overlaps and complete atomic bundles. Freeze requires approved reopen before replacement. "
    "Changed ordinary dependencies become stale atomically; promised bundles cannot partially replace. "
    "Same-content retries return the original committed receipt even after approval expiry.",
)
def apply_authority(proposal_id: UUID, request: AuthorityApplyRequest, application: Application, principal: Principal):
    return application.apply(principal, proposal_id, request)


@router.get(
    "/{scope_id}",
    response_model=AuthorityReadResponse,
    summary="Read selected or historical captured composite authority",
    description="Defaults to LATEST_APPROVED, with explicit EXACT, AS_REPORTED and COMMITTED_TOKEN selectors. "
    "Returns the captured original without calculation or linking, preserving historical decisions and current-use "
    "restrictions separately. Each wider window needs its own captured original. Arbitrary UTC knowledge time "
    "and composite-only imported history are unsupported. A snapshot token identifies committed history; it grants no access.",
)
def read_authority(
    scope_id: Annotated[str, Path(pattern=r"^sha256:[0-9a-f]{64}$")],
    application: Application,
    principal: Principal,
    mode: Literal["LATEST_APPROVED", "EXACT", "AS_REPORTED", "COMMITTED_TOKEN"] = "LATEST_APPROVED",
    decision_id: UUID | None = None,
    token: Annotated[str | None, Query(max_length=128)] = None,
):
    return application.read(principal, scope_id, mode=mode, decision_id=decision_id, token=token)
