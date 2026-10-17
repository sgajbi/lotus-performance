"""Separate v4 annual authority; existing v2/v3 models and hashes stay closed."""

import base64
from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import Field, model_validator

from app.models.composite_authority import (
    AuthorityProvider,
    BusinessDate,
    ControlledScenarioSubjectApprovalBinding,
    Digest,
    EvidenceBinding,
    GovernedCompositeDefinition,
    Identifier,
    Instant,
    MemberIdentity,
    authority_digest,
)
from app.models.composite_controlled_annual_basis import (
    ControlledYearAuthorityRule,
    ControlledYearBasisMapping,
    required_year_facts,
    year_rules_for_window,
)
from app.models.composite_eligibility_evidence import (
    CandidateUniverse,
    EligibilityWire,
    HashedEligibilityWire,
    _equal,
    _month_window,
    _require,
)
from app.models.composite_historical_subject_evidence import HistoricalPolicyReference, _historical_signature


class ControlledYearAuthorityClaims(EligibilityWire):
    schema_version: Literal["controlled-year-authority-approval-claims.v1"]
    purpose: Literal["COMPOSITE_CONTROLLED_YEAR_AUTHORITY"]
    tenant_id: Identifier
    composite_id: Identifier
    definition_version: Identifier
    profile_id: Identifier
    profile_revision: Identifier
    profile_digest: Digest
    definition_payload_digest: Digest
    basis_raw_digest: Digest
    effective_from: BusinessDate
    effective_to: BusinessDate
    approving_identity: Identifier
    approved_at: Instant
    eligibility_evidence_digest: Digest
    method_evidence_digest: Digest


class ControlledYearBasisVerificationRequest(EligibilityWire):
    product_name: Literal["CompositeControlledYearBasisVerificationRequest"]
    product_version: Literal["v1"]
    purpose: Literal["COMPOSITE_CONTROLLED_YEAR_AUTHORITY"]
    operation: Literal["DEFINITION_FINALIZATION"]
    tenant_id: Identifier
    composite_id: Identifier
    definition_version: Identifier
    year: int = Field(strict=True, ge=1900, le=9998)
    revision: Identifier
    actor_id: Identifier
    requested_at: Instant
    intent_digest: Digest
    basis_reference: HistoricalPolicyReference
    profile_configuration_digest: Digest


class ControlledYearBasisVerification(HashedEligibilityWire):
    product_name: Literal["CompositeControlledYearBasisVerification"]
    product_version: Literal["v1"]
    posture: Literal["SYNTHETIC_NON_CERTIFYING"]
    signature_semantics: Literal["SCENARIO_DECLARATION_AT_ACTUAL_ISSUANCE"]
    source_signature_status: Literal["VERIFIED_AT_ACTUAL_ISSUANCE"]
    request: ControlledYearBasisVerificationRequest
    claims: ControlledYearAuthorityClaims
    basis_mapping: ControlledYearBasisMapping
    candidate_evidence: list[CandidateUniverse] = Field(min_length=12, max_length=12)
    source_evidence_digest: Digest
    verifier_id: Identifier
    signer_principal_id: Identifier
    verifier_principal_id: Identifier
    configuration_digest: Digest
    signer_key_digest: Digest
    verifier_key_digest: Digest
    verifier_public_key_base64: str = Field(strict=True, min_length=44, max_length=44)
    revocation_revision: Identifier
    revocation_digest: Digest
    current_revocation_status: Literal["CLEAR"]
    checked_at: Instant
    admitted_at: Instant
    expires_at: Instant
    verifier_credential: str = Field(strict=True, min_length=1, max_length=16384)

    @model_validator(mode="after")
    def exact_verification(self) -> Self:
        basis, request = self.basis_mapping.basis, self.request
        _equal(
            request, basis.scope, ("tenant_id", "composite_id", "definition_version"), "COMPOSITE_YEAR_SCOPE_MISMATCH"
        )
        _require(
            (
                request.basis_reference,
                request.year,
                request.intent_digest,
                request.actor_id,
                request.requested_at,
                request.profile_configuration_digest,
            )
            == (
                self.basis_mapping.reference,
                basis.year,
                authority_digest(self.claims.model_dump()),
                self.claims.approving_identity,
                self.claims.approved_at,
                self.configuration_digest,
            ),
            "COMPOSITE_YEAR_REQUEST_MISMATCH",
        )
        _equal(
            self.claims,
            basis.scope,
            ("tenant_id", "composite_id", "definition_version"),
            "COMPOSITE_YEAR_SCOPE_MISMATCH",
        )
        _require(
            self.claims.basis_raw_digest == self.basis_mapping.reference.raw_digest, "COMPOSITE_YEAR_BASIS_MISMATCH"
        )
        _require(
            self.signer_principal_id == basis.signer_principal_id
            and self.signer_principal_id != self.verifier_principal_id
            and self.signer_key_digest != self.verifier_key_digest,
            "COMPOSITE_YEAR_INDEPENDENCE_REQUIRED",
        )
        _year_candidates(self)
        _year_admission_window(self)
        _canonical_verifier_credential(self)
        _historical_signature(self)
        return self


def _canonical_verifier_credential(proof) -> None:
    for value, size in ((proof.verifier_public_key_base64, 32), (proof.verifier_credential, 64)):
        decoded = base64.b64decode(value, validate=True)
        _require(
            len(decoded) == size and base64.b64encode(decoded).decode() == value,
            "COMPOSITE_YEAR_VERIFIER_CREDENTIAL_INVALID",
        )


def _year_admission_window(proof) -> None:
    checked, requested, admitted, expiry = map(
        datetime.fromisoformat, (proof.checked_at, proof.request.requested_at, proof.admitted_at, proof.expires_at)
    )
    issued = datetime.fromisoformat(proof.basis_mapping.basis.actual_issued_at)
    _require(issued <= requested, "COMPOSITE_YEAR_CLOCK_MISMATCH")
    _require(
        checked <= requested <= admitted < expiry <= checked + timedelta(minutes=5),
        "COMPOSITE_YEAR_ADMISSION_WINDOW_INVALID",
    )


def _year_candidates(proof) -> None:
    basis = proof.basis_mapping.basis
    _require(
        [item.month for item in proof.candidate_evidence] == [item.month for item in basis.months],
        "COMPOSITE_YEAR_MONTH_VECTOR_MISMATCH",
    )
    union: dict[str, MemberIdentity] = {}
    for candidate, selection in zip(proof.candidate_evidence, basis.months, strict=True):
        _annual_candidate(basis, candidate, selection, union, proof.admitted_at)
    _require([union[key] for key in sorted(union)] == basis.member_identities, "COMPOSITE_YEAR_MEMBER_MAP_MISMATCH")
    _require(
        proof.source_evidence_digest
        == authority_digest(
            {
                "basis_mapping": proof.basis_mapping.model_dump(),
                "candidate_evidence": [item.model_dump() for item in proof.candidate_evidence],
            }
        ),
        "COMPOSITE_YEAR_SOURCE_EVIDENCE_MISMATCH",
    )


def _annual_candidate(basis, candidate, selection, union, admitted_at) -> None:
    _equal(
        candidate,
        basis.scope,
        ("tenant_id", "composite_id", "definition_version", "reporting_currency"),
        "COMPOSITE_YEAR_SCOPE_MISMATCH",
    )
    _require(
        candidate.posture == "COMPLETE" and candidate.registry_binding == selection.candidate_registry_binding,
        "COMPOSITE_YEAR_CANDIDATE_BINDING_MISMATCH",
    )
    first, last = _month_window(candidate.month)
    generated = datetime.fromisoformat(candidate.generated_at)
    _require(
        generated.utcoffset() is not None and generated <= datetime.fromisoformat(admitted_at),
        "COMPOSITE_YEAR_CANDIDATE_CLOCK_MISMATCH",
    )
    for identity in candidate.members:
        _require(
            identity.member_id not in union or union[identity.member_id] == identity,
            "COMPOSITE_YEAR_MEMBER_MAP_MISMATCH",
        )
        union[identity.member_id] = identity
        for fact in required_year_facts(basis, identity.member_id, first, last):
            year_rules_for_window(basis, identity.member_id, fact, first, last)


class ControlledYearAuthorityPayload(EligibilityWire):
    product_name: Literal["CompositeSourceAuthority"]
    product_version: Literal["v4"]
    profile_id: Identifier
    profile_revision: Identifier
    tenant_id: Identifier
    composite_id: Identifier
    year: int = Field(strict=True, ge=1900, le=9998)
    effective_from: BusinessDate
    effective_to: BusinessDate
    mode: Literal["INTERNAL"]
    definition_owner: Literal["lotus-manage"]
    membership_owner: Literal["lotus-manage"]
    publisher: Literal["lotus-manage"]
    materialization_owner: Literal["lotus-performance"]
    calculation_owner: Literal["lotus-performance"]
    basis_mapping: ControlledYearBasisMapping
    member_identities: list[MemberIdentity] = Field(min_length=1, max_length=1000)
    providers: list[AuthorityProvider] = Field(min_length=2, max_length=16)
    authority_rules: list[ControlledYearAuthorityRule] = Field(min_length=2, max_length=256)
    eligibility_evaluation_binding: ControlledScenarioSubjectApprovalBinding
    return_method_binding: EvidenceBinding
    source_qualification: Literal["UNQUALIFIED"]
    population_verification: Literal["UNVERIFIED"]

    @model_validator(mode="after")
    def retained_basis(self) -> Self:
        basis = self.basis_mapping.basis
        _equal(
            self,
            basis,
            (
                "profile_id",
                "profile_revision",
                "year",
                "effective_from",
                "effective_to",
                "mode",
                "member_identities",
                "providers",
                "authority_rules",
                "return_method_binding",
            ),
            "COMPOSITE_YEAR_BASIS_MISMATCH",
        )
        _equal(self, basis.scope, ("tenant_id", "composite_id"), "COMPOSITE_YEAR_SCOPE_MISMATCH")
        return self


class ControlledYearAuthorityProfile(EligibilityWire):
    payload: ControlledYearAuthorityPayload
    profile_digest: Digest

    @model_validator(mode="after")
    def exact_profile_digest(self) -> Self:
        _require(
            self.profile_digest == authority_digest(self.payload.model_dump()),
            "COMPOSITE_AUTHORITY_PROFILE_HASH_MISMATCH",
        )
        return self


class ControlledYearAuthorityApproval(EligibilityWire):
    evidence_kind: Literal["VERIFIED_CONTROLLED_YEAR_BASIS"]
    claims: ControlledYearAuthorityClaims
    verification: ControlledYearBasisVerification
    official_activation: Literal["UNAVAILABLE"]


class ControlledAnnualDefinitionV4(HashedEligibilityWire):
    product_name: Literal["CompositeDefinition"]
    product_version: Literal["v4"]
    tenant_id: Identifier
    composite_id: Identifier
    definition_version: Identifier
    display_name: str = Field(strict=True, min_length=1, max_length=256)
    strategy_code: Identifier
    reporting_currency: str = Field(strict=True, pattern=r"^[A-Z]{3}$")
    inception_date: BusinessDate
    termination_date: BusinessDate | None
    calculation_method: Literal["ASSET_WEIGHTED"]
    eligibility_policy_version: Identifier
    source_authority: ControlledYearAuthorityProfile
    created_at: Instant
    created_by: Identifier
    correlation_id: Identifier
    definition_payload_digest: Digest
    authority_approval: ControlledYearAuthorityApproval

    @model_validator(mode="after")
    def authority_links(self) -> Self:
        payload, approval = self.source_authority.payload, self.authority_approval
        basis, claims = payload.basis_mapping.basis, approval.claims
        _equal(
            self,
            basis.scope,
            (
                "tenant_id",
                "composite_id",
                "definition_version",
                "strategy_code",
                "reporting_currency",
                "eligibility_policy_version",
            ),
            "COMPOSITE_YEAR_SCOPE_MISMATCH",
        )
        _require(
            self.inception_date <= basis.effective_from
            and (self.termination_date is None or self.termination_date >= basis.effective_to),
            "COMPOSITE_YEAR_WINDOW_MISMATCH",
        )
        _require(
            self.created_by != claims.approving_identity and self.created_at <= claims.approved_at,
            "COMPOSITE_YEAR_CHECKER_MISMATCH",
        )
        _require(
            self.source_authority.profile_digest == authority_digest(payload.model_dump()),
            "COMPOSITE_AUTHORITY_PROFILE_HASH_MISMATCH",
        )
        _require(
            self.definition_payload_digest
            == authority_digest(
                self.model_dump(exclude={"content_hash", "definition_payload_digest", "authority_approval"})
            ),
            "COMPOSITE_AUTHORITY_DEFINITION_HASH_MISMATCH",
        )
        _equal(
            claims,
            self,
            ("tenant_id", "composite_id", "definition_version", "definition_payload_digest"),
            "COMPOSITE_YEAR_CLAIMS_MISMATCH",
        )
        _equal(
            claims,
            payload,
            ("profile_id", "profile_revision", "effective_from", "effective_to"),
            "COMPOSITE_YEAR_CLAIMS_MISMATCH",
        )
        _require(
            (claims.profile_digest, claims.eligibility_evidence_digest, claims.method_evidence_digest)
            == (
                self.source_authority.profile_digest,
                payload.eligibility_evaluation_binding.digest,
                payload.return_method_binding.digest,
            ),
            "COMPOSITE_YEAR_CLAIMS_MISMATCH",
        )
        _require(
            approval.verification.claims == claims and approval.verification.basis_mapping == payload.basis_mapping,
            "COMPOSITE_YEAR_BASIS_MISMATCH",
        )
        return self

    def performance_definition(self):
        from app.models.composite_controlled_scenario_definition import ControlledAnnualCompositeDefinition

        fields = (
            "composite_id",
            "display_name",
            "strategy_code",
            "reporting_currency",
            "inception_date",
            "termination_date",
            "calculation_method",
            "source_authority",
        )
        return ControlledAnnualCompositeDefinition.model_validate({field: getattr(self, field) for field in fields})


SupportedGovernedCompositeDefinition = GovernedCompositeDefinition | ControlledAnnualDefinitionV4
