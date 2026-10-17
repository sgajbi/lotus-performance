"""Evaluated January publication v5; pending preparation is never eligibility."""

from typing import Literal, Self

from pydantic import Field, model_validator

from app.models.composite_authority import ControlledScenarioSubjectApprovalBinding, EvidenceBinding, authority_digest
from app.models.composite_controlled_annual_authority import (
    ControlledAnnualDefinitionV4,
    ControlledYearBasisVerification,
)
from app.models.composite_controlled_scenario_evidence import ControlledScenarioSubjectEvaluationApproval
from app.models.composite_eligibility_evidence import (
    EligibilitySubject,
    HashedEligibilityWire,
    VerificationReceipt,
    _equal,
    _method_verification,
    _require,
)


class ControlledAnnualFinalization(HashedEligibilityWire):
    product_name: Literal["CompositeEligibilityFinalization"]
    product_version: Literal["v5"]
    official_activation: Literal["UNAVAILABLE"]
    subject: EligibilitySubject
    evaluation_approval: ControlledScenarioSubjectEvaluationApproval
    definition: ControlledAnnualDefinitionV4
    year_authority_verification: ControlledYearBasisVerification
    verifications: list[VerificationReceipt] = Field(min_length=2, max_length=258)

    @model_validator(mode="after")
    def evaluated_first_publication(self) -> Self:
        definition, approval, subject = self.definition, self.evaluation_approval, self.subject
        payload = definition.source_authority.payload
        proof = self.year_authority_verification
        _require(
            subject == approval.proposal.policy_approval.proposal.subject,
            "COMPOSITE_SUBJECT_FINALIZATION_SCOPE_MISMATCH",
        )
        _equal(
            subject,
            definition,
            (
                "tenant_id",
                "composite_id",
                "definition_version",
                "display_name",
                "strategy_code",
                "reporting_currency",
                "inception_date",
                "termination_date",
                "eligibility_policy_version",
                "created_by",
                "created_at",
                "correlation_id",
            ),
            "COMPOSITE_SUBJECT_FINALIZATION_SCOPE_MISMATCH",
        )
        _require(subject.month == f"{payload.year:04d}-01", "COMPOSITE_YEAR_FIRST_MONTH_MISMATCH")
        _require(subject.universe == proof.candidate_evidence[0], "COMPOSITE_YEAR_CANDIDATE_BINDING_MISMATCH")
        _require(proof == definition.authority_approval.verification, "COMPOSITE_YEAR_BASIS_MISMATCH")
        _require(proof.request.revision == subject.subject_revision, "COMPOSITE_YEAR_REQUEST_MISMATCH")
        _require(
            payload.eligibility_evaluation_binding
            == ControlledScenarioSubjectApprovalBinding(
                product_name=approval.product_name,
                product_version=approval.product_version,
                revision=approval.proposal.evaluation_revision,
                digest=approval.content_hash,
            ),
            "COMPOSITE_SUBJECT_ELIGIBILITY_BINDING_MISMATCH",
        )
        _require(
            payload.basis_mapping.basis.months[0].monthly_policy_reference
            == approval.proposal.policy_approval.approval.proposal.verification.mapping.reference,
            "COMPOSITE_YEAR_POLICY_REFERENCE_MISMATCH",
        )
        _require(
            definition.authority_approval.claims.approved_at >= approval.approved_at,
            "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH",
        )
        _annual_verifications(self)
        return self


def _annual_verifications(finalization) -> None:
    requests = [receipt.request for receipt in finalization.verifications]
    payload = finalization.definition.source_authority.payload
    for receipt in finalization.verifications:
        request = receipt.request
        _require(receipt.posture == "SYNTHETIC_NON_CERTIFYING", "COMPOSITE_YEAR_POSTURE_UNAVAILABLE")
        _equal(
            request,
            finalization.subject,
            ("tenant_id", "composite_id", "definition_version"),
            "COMPOSITE_VERIFICATION_SCOPE_MISMATCH",
        )
        _require(
            request.subject_content_hash == finalization.subject.content_hash, "COMPOSITE_VERIFICATION_SUBJECT_MISMATCH"
        )
    _method_verification(finalization.definition, requests)
    expected = _annual_provider_requests(payload)
    method = requests[0]
    _require(
        method.purpose == "RETURN_METHOD_CALENDAR"
        and (method.effective_from, method.effective_to) == (payload.effective_from, payload.effective_to),
        "COMPOSITE_YEAR_VERIFICATION_WINDOW_MISMATCH",
    )
    actual = [
        (request.source_product, request.binding, request.effective_from, request.effective_to, request.claims_digest)
        for request in requests[1:]
        if request.purpose == "PROVIDER_REGISTRATION"
    ]
    _require(
        actual == expected and len(requests) == len(expected) + 1, "COMPOSITE_VERIFICATION_PROVIDER_BINDING_MISMATCH"
    )


def _annual_provider_requests(payload) -> list:
    providers = {item.provider_id: item for item in payload.providers}
    return [
        (
            rule.source_product,
            EvidenceBinding(
                product_name="CompositeProviderRegistration",
                product_version="v1",
                revision=providers[rule.provider_id].registry_revision,
                digest=providers[rule.provider_id].registry_digest,
            ),
            rule.effective_from,
            rule.effective_to,
            authority_digest(
                {
                    "provider": providers[rule.provider_id].model_dump(),
                    "source_product": rule.source_product,
                    "effective_from": rule.effective_from,
                    "effective_to": rule.effective_to,
                }
            ),
        )
        for rule in payload.authority_rules
    ]


class ControlledAnnualFinalizationReceipt(HashedEligibilityWire):
    product_name: Literal["CompositeEligibilityFinalizationReceipt"]
    product_version: Literal["v5"]
    finalization: ControlledAnnualFinalization
    publication_sequence: int = Field(strict=True, ge=1)
    membership_content_hash: str = Field(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")
    universe_content_hash: str = Field(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")
    completeness: Literal["UNVERIFIED"]

    @model_validator(mode="after")
    def publication_hashes(self) -> Self:
        _equal(
            self,
            self.finalization.evaluation_approval,
            ("membership_content_hash", "universe_content_hash"),
            "COMPOSITE_SUBJECT_PUBLICATION_HASH_MISMATCH",
        )
        return self
