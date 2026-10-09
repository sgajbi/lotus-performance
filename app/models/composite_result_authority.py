"""Strict nonfinancial commands and receipts for captured-original authority."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.composite_authority import Digest, Identifier
from app.models.composite_result_candidates import CompositeResultCandidateResponse


class AuthorityAction(StrEnum):
    SELECT_INITIAL = "SELECT_INITIAL"
    REPLACE = "REPLACE"
    FREEZE = "FREEZE"
    REOPEN = "REOPEN"
    RESTORE_PRIOR = "RESTORE_PRIOR"
    WITHDRAW_CURRENT_USE = "WITHDRAW_CURRENT_USE"


class AuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthorityTarget(AuthorityModel):
    candidate_id: UUID
    expected_revision: Annotated[int, Field(ge=0, strict=True)]


class AuthorityProposalRequest(AuthorityModel):
    proposal_id: UUID
    action: AuthorityAction
    targets: list[AuthorityTarget] = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=20)
    bundle_id: UUID | None = None

    @model_validator(mode="after")
    def bounded_atomic_selection(self):
        identities = [target.candidate_id for target in self.targets]
        if len(set(identities)) != len(identities):
            raise ValueError("Authority targets must be unique")
        if len(identities) > 1 and self.bundle_id is None:
            raise ValueError("Multiple authority targets require an explicit atomic bundle")
        return self


class AuthorityApprovalRequest(AuthorityModel):
    approval_id: UUID
    financial_evidence: str = Field(min_length=1, max_length=65536)


class AuthorityApplyRequest(AuthorityModel):
    decision_id: UUID
    approval_id: UUID


class AuthorityScope(AuthorityModel):
    scope_id: Digest
    base_id: Digest
    composite_id: Identifier
    period_start: date
    period_end: date
    return_view: Literal["GROSS", "NET_ACTUAL", "NET_MODEL_FEE"]
    reporting_currency: str = Field(pattern=r"^[A-Z]{3}$")
    method_family: Literal["ASSET_WEIGHTED_COMPOSITE_TWR"]


class AuthorityWindow(AuthorityModel):
    period_start: date
    period_end: date
    materialization_id: UUID
    retained_digest: Digest


class AuthorityVector(AuthorityModel):
    scope: AuthorityScope
    candidate_id: UUID
    original_response_digest: str
    vector_digest: Digest
    windows: list[AuthorityWindow] = Field(min_length=1, max_length=120)
    maker_subjects: list[str] = Field(min_length=1, max_length=1000)


class AuthorityImpact(AuthorityModel):
    affected_scope_ids: list[Digest]
    dependency_revision_digest: Digest
    report_versions: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    recipients: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    materiality_policy: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    numerical_recalculation: Literal["NOT_PERFORMED"] = "NOT_PERFORMED"


class AuthorityActor(AuthorityModel):
    subject: str
    principal_kind: str
    credential_id: str
    delegated_actor: str | None = None


class AuthorityProposalResponse(AuthorityModel):
    proposal_id: UUID
    proposal_digest: Digest
    maker_subject: str
    maker: AuthorityActor
    action: AuthorityAction
    targets: list[AuthorityVector]
    expected_revisions: dict[str, int]
    bundle_id: UUID | None
    reason: str
    evidence_refs: list[str]
    impact: AuthorityImpact
    created_at_utc: datetime
    qualification: Literal["UNAPPROVED_PROPOSAL"] = "UNAPPROVED_PROPOSAL"


class AuthorityApprovalResponse(AuthorityModel):
    approval_id: UUID
    proposal_id: UUID
    proposal_digest: Digest
    checker_subject: str
    canonical_checker: str
    policy_digest: Digest
    evidence_digest: Digest
    valid_until: datetime
    qualification: Literal["SYNTHETIC_NON_CERTIFYING"] = "SYNTHETIC_NON_CERTIFYING"


class AuthoritySelection(AuthorityModel):
    scope: AuthorityScope
    revision: int = Field(ge=1)
    candidate_id: UUID
    vector_digest: Digest
    frozen: bool
    current_use: Literal["SELECTED", "STALE", "WITHDRAWN"]
    bundle_id: UUID | None


class AuthorityDecisionResponse(AuthorityModel):
    decision_id: UUID
    proposal_id: UUID
    approval_id: UUID
    action: AuthorityAction
    actor: AuthorityActor
    selections: list[AuthoritySelection]
    stale_scope_ids: list[Digest]
    snapshot_token: str
    recorded_at_utc: datetime
    qualification: Literal["SYNTHETIC_NON_CERTIFYING"] = "SYNTHETIC_NON_CERTIFYING"


class AuthorityReadResponse(AuthorityModel):
    selection_mode: Literal["LATEST_APPROVED", "EXACT", "AS_REPORTED", "COMMITTED_TOKEN"]
    decision: AuthorityDecisionResponse
    selection: AuthoritySelection
    original: CompositeResultCandidateResponse
    current_use: Literal["SELECTED", "STALE", "WITHDRAWN"]
    pending_impact_count: int = Field(ge=0)
    materiality_assessment: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    institution_activation: Literal["UNAVAILABLE"] = "UNAVAILABLE"
