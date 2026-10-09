"""Strict consumer projections of Manage's staged eligibility lifecycle.

Legacy producer snapshot SHA256 af64f94e52ff4876f21df7ca8706bd1b32271cf753a300756d793c3130f93122.
Retained monthly assembly is an optional producer-version extension: absent legacy
evidence remains absent from hashes. Other wire fields remain required.
These models decode evidence; they do not confer institutional trust or publication.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_serializer, model_validator

from app.models.composite_authority import (
    AuthorityWire,
    BusinessDate,
    Digest,
    EvidenceBinding,
    Identifier,
    Instant,
    ManageCompositeDefinitionV2,
    MemberIdentity,
    authority_digest,
    decode_authority_json,
)

if TYPE_CHECKING:
    from app.models.composite_monthly_eligibility_evidence import CompositeMonthlyEligibilityPublicationReceipt

_SCOPE = ("tenant_id", "composite_id", "definition_version")
_BUSINESS_DATES = frozenset(
    {
        "business_date",
        "cash_as_of",
        "coverage_from",
        "coverage_to",
        "effective_from",
        "effective_to",
        "flow_coverage_from",
        "flow_coverage_to",
        "inception_date",
        "prior_assets_as_of",
        "readiness_as_of",
        "termination_date",
    }
)
_INSTANTS = frozenset(
    {"approved_at", "created_at", "evaluated_at", "generated_at", "proposed_at", "received_at", "source_generated_at"}
)


def _equal(expected: Any, actual: Any, fields: tuple[str, ...], code: str) -> None:
    if any(getattr(expected, field) != getattr(actual, field) for field in fields):
        raise ValueError(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _month_window(month: str) -> tuple[str, str]:
    start = date.fromisoformat(month + "-01")
    return start.isoformat(), start.replace(day=calendar.monthrange(start.year, start.month)[1]).isoformat()


class EligibilityWire(AuthorityWire):
    @field_validator("*")
    @classmethod
    def calendar_strings(cls, value: Any, info: ValidationInfo) -> Any:
        if value is not None and info.field_name in _BUSINESS_DATES:
            date.fromisoformat(value)
        if value is not None and info.field_name in _INSTANTS:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
        return value


class HashedEligibilityWire(EligibilityWire):
    content_hash: Digest

    @model_validator(mode="after")
    def envelope_digest(self) -> Self:
        _require(
            authority_digest(self.model_dump(exclude={"content_hash"})) == self.content_hash,
            "COMPOSITE_ELIGIBILITY_CONTENT_HASH_MISMATCH",
        )
        return self


class MonthlyRuleAssessment(EligibilityWire):
    admitted_flow_count: Annotated[int, Field(le=250, ge=0)] | None
    denominator: Annotated[str, Field(max_length=160)] | None
    failure_reasons: list[str]
    gross_inflow: str | None
    gross_outflow: str | None
    numerator: Annotated[str, Field(max_length=160)] | None
    outcome: Literal["PASS", "FAIL", "UNKNOWN"]
    ratio: Annotated[str, Field(max_length=160)] | None
    rule: Literal["SIGNIFICANT_FLOW", "CASH", "READINESS"]
    unknown_reasons: list[str]


class MonthlyPortfolioEvaluation(EligibilityWire):
    assessments: list[MonthlyRuleAssessment] = Field(min_length=3, max_length=3)
    observations_present: bool
    portfolio_id: Identifier
    status: Literal["INCLUDED", "EXCLUDED", "PENDING_REVIEW"]


class MonthlyPolicyLayer(EligibilityWire):
    cash_threshold: Annotated[str, Field(pattern="^(?:0(?:\\.\\d{1,12})?|1(?:\\.0{1,12})?)$")] | None
    composite_id: Identifier | None
    effective_from: BusinessDate
    effective_to: BusinessDate
    flow_threshold: Annotated[str, Field(pattern="^(?:0(?:\\.\\d{1,12})?|1(?:\\.0{1,12})?)$")] | None
    level: Literal["PLATFORM", "TENANT", "STRATEGY", "COMPOSITE", "RUN"]
    permitted_overrides: list[Literal["CASH_THRESHOLD", "FLOW_THRESHOLD"]] = Field(max_length=2)
    policy_id: Identifier
    revision: Identifier
    run_id: Identifier | None
    strategy_code: Identifier | None
    tenant_id: Identifier | None


class MonthlyPolicyScope(EligibilityWire):
    composite_id: Identifier
    definition_version: Identifier
    run_id: Identifier | None
    strategy_code: Identifier
    tenant_id: Identifier


class ResolvedMonthlyPolicy(HashedEligibilityWire):
    cash_breach_operator: Literal["GREATER_THAN"]
    cash_denominator: Literal["MONTH_END_NET_ASSETS"]
    cash_numerator: Literal["SETTLED_UNENCUMBERED_CASH_ONLY"]
    cash_threshold: Annotated[str, Field(pattern="^(?:0(?:\\.\\d{1,12})?|1(?:\\.0{1,12})?)$")]
    currency_treatment: Literal["SOURCE_NORMALIZED_SINGLE_CURRENCY"]
    evaluation_timing: Literal["AFTER_MONTH_END"]
    flow_breach_operator: Literal["GREATER_THAN_OR_EQUAL"]
    flow_date_basis: Literal["SOURCE_BUSINESS_DATE_UTC"]
    flow_denominator: Literal["PRIOR_MONTH_END_NET_ASSETS"]
    flow_measure: Literal["ABS_NET"]
    flow_threshold: Annotated[str, Field(pattern="^(?:0(?:\\.\\d{1,12})?|1(?:\\.0{1,12})?)$")]
    holiday_treatment: Literal["NO_DATE_SHIFT"]
    layers: list[MonthlyPolicyLayer] = Field(min_length=1, max_length=5)
    membership_frequency: Literal["CALENDAR_MONTH"]
    missing_data: Literal["REQUIRED_UNKNOWN"]
    month: Annotated[str, Field(pattern="^\\d{4}-\\d{2}$")]
    observation_window: Literal["WHOLE_TARGET_MONTH"]
    official_activation: Literal["UNAVAILABLE"]
    product_name: Literal["CompositeMonthlyEligibilityPolicy"]
    product_version: Literal["v1"]
    profile_kind: Literal["SYNTHETIC_MONTHLY_ABS_NET_CASH_READINESS"]
    ratio_unit: Literal["DECIMAL_FRACTION"]
    reentry: Literal["REEVALUATE_ALL_NEXT_MONTH_RULES"]
    scope: MonthlyPolicyScope
    source_cut_timing: Literal["AFTER_MONTH_END"]


class MonthlyEligibilityEvaluation(HashedEligibilityWire):
    composite_id: Identifier
    declared_universe_coverage: Literal["COMPLETE", "INCOMPLETE"]
    definition_version: Identifier
    evaluated_at: Instant
    evidence_class: Literal["SYNTHETIC_UNQUALIFIED", "SOURCE_UNVERIFIED"]
    excluded_count: Annotated[int, Field(le=1000, ge=0)]
    expected_count: Annotated[int, Field(le=1000, ge=1)]
    included_count: Annotated[int, Field(le=1000, ge=0)]
    input_content_hash: Digest
    month: str
    observed_count: Annotated[int, Field(le=1000, ge=0)]
    official_activation: Literal["UNAVAILABLE"]
    pending_review_count: Annotated[int, Field(le=1000, ge=0)]
    population_verification: Literal["UNVERIFIED"]
    portfolios: list[MonthlyPortfolioEvaluation] = Field(min_length=1, max_length=1000)
    product_name: Literal["CompositeMonthlyEligibilityEvaluation"]
    product_version: Literal["v1"]
    resolved_policy: ResolvedMonthlyPolicy
    source_cut_id: Identifier
    source_revision: Identifier
    tenant_id: Identifier
    universe_content_hash: Digest


class DpmCompositeUniverseSourceProduct(EligibilityWire):
    authority_scope: Literal["AUTHORITATIVE_UNIVERSE", "POLICY_INPUT", "REFERENCE_INPUT"]
    content_hash: str
    contract_version: str
    owner_service: str
    product_name: str
    source_cut_id: str
    source_watermark: str


class MonthlyFlowObservation(EligibilityWire):
    amount: Annotated[str, Field(pattern="^-?(?:0|[1-9]\\d{0,23})(?:\\.\\d{1,12})?$")]
    business_date: BusinessDate
    classification: Literal["EXTERNAL_CASH", "INTERNAL_TRANSFER", "REVERSAL", "IN_KIND"]
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    event_id: Identifier
    received_at: Instant
    reverses_event_id: Identifier | None
    status: Literal["POSTED", "CANCELLED"]


class MonthlyPortfolioObservations(EligibilityWire):
    cash_as_of: BusinessDate | None
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    discretionary: bool | None
    flow_coverage_from: BusinessDate | None
    flow_coverage_to: BusinessDate | None
    flows: list[MonthlyFlowObservation] = Field(max_length=250)
    funded: bool | None
    invested: bool | None
    month_end_assets: Annotated[str, Field(pattern="^-?(?:0|[1-9]\\d{0,23})(?:\\.\\d{1,12})?$")] | None
    portfolio_id: Identifier
    prior_assets_as_of: BusinessDate | None
    prior_month_end_assets: Annotated[str, Field(pattern="^-?(?:0|[1-9]\\d{0,23})(?:\\.\\d{1,12})?$")] | None
    readiness_as_of: BusinessDate | None
    settled_unencumbered_cash: Annotated[str, Field(pattern="^-?(?:0|[1-9]\\d{0,23})(?:\\.\\d{1,12})?$")] | None


class MonthlyEligibilityObservations(EligibilityWire):
    composite_id: Identifier
    definition_version: Identifier
    evidence_class: Literal["SYNTHETIC_UNQUALIFIED", "SOURCE_UNVERIFIED"]
    expected_portfolio_ids: list[Identifier] = Field(min_length=1, max_length=1000)
    month: str
    portfolios: list[MonthlyPortfolioObservations] = Field(max_length=1000)
    product_name: Literal["CompositeMonthlyEligibilityObservations"]
    product_version: Literal["v1"]
    reporting_currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    source_cut_id: Identifier
    source_generated_at: Instant
    source_revision: Identifier
    tenant_id: Identifier


class MonthlyPolicyProposal(HashedEligibilityWire):
    attachments: list[EvidenceBinding] = Field(min_length=1, max_length=20)
    eligibility_policy_version: Identifier
    policy: ResolvedMonthlyPolicy
    product_name: Literal["CompositeMonthlyPolicyProposal"]
    product_version: Literal["v1"]
    proposal_revision: Identifier
    proposed_at: Instant
    proposed_by: Identifier


class MonthlyPolicyApproval(HashedEligibilityWire):
    approved_at: Instant
    approved_by: Identifier
    evidence_kind: Literal["SYNTHETIC_UNSIGNED"]
    official_activation: Literal["UNAVAILABLE"]
    product_name: Literal["CompositeMonthlyPolicyApproval"]
    product_version: Literal["v1"]
    proposal: MonthlyPolicyProposal


class CandidateUniverse(HashedEligibilityWire):
    composite_id: Identifier
    coverage_from: BusinessDate
    coverage_to: BusinessDate
    definition_version: Identifier
    generated_at: Instant
    members: list[MemberIdentity] = Field(min_length=1, max_length=1000)
    month: str
    observation_owner: Identifier
    population_verification: Literal["UNVERIFIED"]
    posture: Literal["COMPLETE", "INCOMPLETE", "UNAVAILABLE"]
    product_name: Literal["CompositeEligibilityCandidateUniverse"]
    product_version: Literal["v1"]
    registry_binding: EvidenceBinding
    reporting_currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    source_cut_id: Identifier
    source_products: list[DpmCompositeUniverseSourceProduct] = Field(min_length=1, max_length=19)
    tenant_id: Identifier

    @model_validator(mode="after")
    def universe_links(self) -> Self:
        ids = [member.member_id for member in self.members]
        _require(ids == sorted(set(ids)), "COMPOSITE_SUBJECT_MEMBER_MAP_MISMATCH")
        _require(
            (self.coverage_from, self.coverage_to) == _month_window(self.month), "COMPOSITE_SUBJECT_WINDOW_MISMATCH"
        )
        products = [product for product in self.source_products if product.authority_scope == "AUTHORITATIVE_UNIVERSE"]
        _require(len(products) == 1, "COMPOSITE_SUBJECT_REGISTRY_BINDING_MISMATCH")
        product = products[0]
        _require(
            (product.product_name, product.contract_version, product.source_watermark, product.content_hash)
            == (
                self.registry_binding.product_name,
                self.registry_binding.product_version,
                self.registry_binding.revision,
                self.registry_binding.digest,
            ),
            "COMPOSITE_SUBJECT_REGISTRY_BINDING_MISMATCH",
        )
        _require(product.source_cut_id == self.source_cut_id, "COMPOSITE_SUBJECT_SOURCE_CUT_MISMATCH")
        return self


class EligibilitySubject(HashedEligibilityWire):
    composite_id: Identifier
    correlation_id: Identifier
    created_at: Instant
    created_by: Identifier
    definition_version: Identifier
    display_name: Annotated[str, Field(max_length=256, min_length=1)]
    eligibility_policy_version: Identifier
    inception_date: BusinessDate
    month: str
    product_name: Literal["CompositeEligibilitySubject"]
    product_version: Literal["v1"]
    reporting_currency: Annotated[str, Field(pattern="^[A-Z]{3}$")]
    strategy_code: Identifier
    subject_revision: Identifier
    tenant_id: Identifier
    termination_date: BusinessDate | None
    universe: CandidateUniverse

    @model_validator(mode="after")
    def subject_links(self) -> Self:
        _equal(
            self, self.universe, _SCOPE + ("month", "reporting_currency"), "COMPOSITE_SUBJECT_UNIVERSE_SCOPE_MISMATCH"
        )
        _require(
            self.termination_date is None or self.termination_date >= self.inception_date,
            "COMPOSITE_SUBJECT_WINDOW_MISMATCH",
        )
        return self


class SubjectPolicyProposal(HashedEligibilityWire):
    product_name: Literal["CompositeSubjectPolicyProposal"]
    product_version: Literal["v1"]
    proposal: MonthlyPolicyProposal
    subject: EligibilitySubject

    @model_validator(mode="after")
    def policy_links(self) -> Self:
        policy = self.proposal.policy
        _equal(self.subject, policy.scope, _SCOPE + ("strategy_code",), "COMPOSITE_SUBJECT_POLICY_SCOPE_MISMATCH")
        _require(policy.month == self.subject.month, "COMPOSITE_SUBJECT_POLICY_SCOPE_MISMATCH")
        _require(
            self.proposal.eligibility_policy_version == self.subject.eligibility_policy_version,
            "COMPOSITE_SUBJECT_POLICY_SCOPE_MISMATCH",
        )
        _require(
            self.subject.universe.registry_binding in self.proposal.attachments,
            "COMPOSITE_SUBJECT_REGISTRY_BINDING_MISMATCH",
        )
        _require(self.subject.created_at <= self.proposal.proposed_at, "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH")
        _require(
            self.proposal.proposed_at[:10] < _month_window(self.subject.month)[0],
            "COMPOSITE_ELIGIBILITY_POLICY_NOT_PROSPECTIVE",
        )
        return self


class VerificationRequest(EligibilityWire):
    binding: EvidenceBinding | None
    claims_digest: Digest
    composite_id: Identifier
    definition_version: Identifier
    effective_from: str
    effective_to: str
    purpose: Literal[
        "ELIGIBILITY_POLICY",
        "ELIGIBILITY_POLICY_EVALUATION",
        "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE",
        "RETURN_METHOD_CALENDAR",
        "PROVIDER_REGISTRATION",
        "COMPOSITE_MONTHLY_SOURCE_CUT",
    ]
    source_product: Identifier | None
    subject_content_hash: Digest
    tenant_id: Identifier

    @model_validator(mode="after")
    def request_window(self) -> Self:
        _require(
            date.fromisoformat(self.effective_from) <= date.fromisoformat(self.effective_to),
            "COMPOSITE_VERIFICATION_WINDOW_MISMATCH",
        )
        return self


class VerificationReceipt(HashedEligibilityWire):
    artifact_digest: Digest
    artifact_revision: Identifier
    issuer_id: Identifier
    posture: Literal["SYNTHETIC_NON_CERTIFYING", "QUALIFIED_RECEIPT"]
    product_name: Literal["CompositeEvidenceVerificationReceipt"]
    product_version: Literal["v1"]
    request: VerificationRequest
    verifier_id: Identifier


class MonthlyInputBinding(EligibilityWire):
    kind: Literal["PRIOR_ASSETS", "MONTH_END_ASSETS", "CASH", "READINESS", "FLOWS"]
    owner_service: Identifier
    source_cut_id: Identifier
    evidence: EvidenceBinding


class MonthlySourceAssembly(EligibilityWire):
    product_name: Literal["CompositeMonthlyEligibilityAssembly"]
    product_version: Literal["v1"]
    observations: MonthlyEligibilityObservations
    inputs: list[MonthlyInputBinding] = Field(min_length=5, max_length=5)
    compatibility_binding: EvidenceBinding
    compatibility_posture: Literal["SYNTHETIC_UNQUALIFIED", "SOURCE_UNVERIFIED", "UNAVAILABLE"]

    @model_validator(mode="after")
    def assembly_links(self) -> Self:
        kinds = [item.kind for item in self.inputs]
        _require(
            set(kinds) == {"PRIOR_ASSETS", "MONTH_END_ASSETS", "CASH", "READINESS", "FLOWS"},
            "COMPOSITE_SOURCE_ASSEMBLY_INPUTS_INCOMPLETE",
        )
        _require(kinds == sorted(kinds), "COMPOSITE_SOURCE_ASSEMBLY_INPUTS_NONCANONICAL")
        _require(
            self.compatibility_binding.product_name == "CompositeSourceCutCompatibility",
            "COMPOSITE_SOURCE_COMPATIBILITY_BINDING_INVALID",
        )
        _require(
            self.compatibility_binding.digest
            == authority_digest(
                {"observations": self.observations.model_dump(), "inputs": [item.model_dump() for item in self.inputs]}
            ),
            "COMPOSITE_SOURCE_COMPATIBILITY_CONTENT_MISMATCH",
        )
        return self


def monthly_assembly_verification_request(assembly: MonthlySourceAssembly) -> VerificationRequest:
    observations = assembly.observations
    first, last = _month_window(observations.month)
    return VerificationRequest(
        purpose="COMPOSITE_MONTHLY_SOURCE_CUT",
        tenant_id=observations.tenant_id,
        composite_id=observations.composite_id,
        definition_version=observations.definition_version,
        subject_content_hash=authority_digest(observations.model_dump()),
        claims_digest=authority_digest(assembly.model_dump()),
        effective_from=first,
        effective_to=last,
        binding=assembly.compatibility_binding,
        source_product=assembly.product_name,
    )


class VerifiedMonthlySourceAssembly(EligibilityWire):
    assembly: MonthlySourceAssembly
    verification: VerificationReceipt

    @model_validator(mode="after")
    def assembly_verification_links(self) -> Self:
        self.assembly = MonthlySourceAssembly.model_validate(self.assembly.model_dump())
        self.verification = VerificationReceipt.model_validate(self.verification.model_dump())
        _require(
            self.assembly.compatibility_posture == "SYNTHETIC_UNQUALIFIED"
            and self.assembly.observations.evidence_class == "SYNTHETIC_UNQUALIFIED"
            and self.verification.posture == "SYNTHETIC_NON_CERTIFYING"
            and self.verification.request == monthly_assembly_verification_request(self.assembly),
            "COMPOSITE_SOURCE_ASSEMBLY_VERIFICATION_MISMATCH",
        )
        return self


def retained_monthly_source_assembly(
    evidence: VerifiedMonthlySourceAssembly | None, observations: MonthlyEligibilityObservations
) -> VerifiedMonthlySourceAssembly | None:
    if evidence is None:
        return None
    verified = VerifiedMonthlySourceAssembly.model_validate(evidence.model_dump())
    _require(verified.assembly.observations == observations, "COMPOSITE_SOURCE_ASSEMBLY_OBSERVATIONS_MISMATCH")
    return verified


class SubjectPolicyApproval(HashedEligibilityWire):
    approval: MonthlyPolicyApproval
    product_name: Literal["CompositeSubjectPolicyApproval"]
    product_version: Literal["v1"]
    proposal: SubjectPolicyProposal
    verification: VerificationReceipt

    @model_validator(mode="after")
    def approval_links(self) -> Self:
        _require(self.approval.proposal == self.proposal.proposal, "COMPOSITE_SUBJECT_POLICY_BINDING_MISMATCH")
        _require(
            self.approval.approved_by != self.approval.proposal.proposed_by,
            "COMPOSITE_ELIGIBILITY_SELF_APPROVAL_FORBIDDEN",
        )
        _require(
            self.approval.approved_at >= self.approval.proposal.proposed_at, "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH"
        )
        _require(
            self.approval.approved_at[:10] < _month_window(self.proposal.subject.month)[0],
            "COMPOSITE_ELIGIBILITY_POLICY_NOT_PROSPECTIVE",
        )
        _verification_subject(self.verification.request, self.proposal.subject, "ELIGIBILITY_POLICY")
        _require(
            self.verification.request.binding is None and self.verification.request.source_product is None,
            "COMPOSITE_VERIFICATION_BINDING_MISMATCH",
        )
        return self


class SubjectEvaluationProposal(HashedEligibilityWire):
    evaluation: MonthlyEligibilityEvaluation
    evaluation_kind: Literal["INITIAL"]
    evaluation_revision: Identifier
    observation_binding: DpmCompositeUniverseSourceProduct
    observations: MonthlyEligibilityObservations
    source_assembly_evidence: VerifiedMonthlySourceAssembly | None = None
    policy_approval: SubjectPolicyApproval
    product_name: Literal["CompositeSubjectEvaluationProposal"]
    product_version: Literal["v1"]
    proposed_at: Instant
    proposed_by: Identifier
    target_membership_revision: Identifier

    @model_serializer(mode="wrap")
    def legacy_optional_assembly_wire(self, handler: Any) -> dict[str, Any]:
        # Pydantic2.11 does not support Field.exclude_if. Preserve the producer's
        # canonical omission without changing other fields or dropping evidence.
        payload: dict[str, Any] = handler(self)
        if self.source_assembly_evidence is None:
            payload.pop("source_assembly_evidence", None)
        return payload

    @model_validator(mode="before")
    @classmethod
    def canonical_optional_assembly_field(cls, value: Any) -> Any:
        if (
            isinstance(value, dict)
            and "source_assembly_evidence" in value
            and value["source_assembly_evidence"] is None
        ):
            raise ValueError("COMPOSITE_SOURCE_ASSEMBLY_NONCANONICAL_NULL")
        return value

    @model_validator(mode="after")
    def evaluation_links(self) -> Self:
        self.source_assembly_evidence = retained_monthly_source_assembly(
            self.source_assembly_evidence, self.observations
        )
        subject = self.policy_approval.proposal.subject
        _equal(
            subject,
            self.observations,
            _SCOPE + ("month", "reporting_currency"),
            "COMPOSITE_SUBJECT_OBSERVATION_SCOPE_MISMATCH",
        )
        _equal(subject, self.evaluation, _SCOPE + ("month",), "COMPOSITE_SUBJECT_EVALUATION_SCOPE_MISMATCH")
        _observation_links(self, subject)
        _evaluation_members(self, subject)
        _require(
            self.evaluation.resolved_policy == self.policy_approval.approval.proposal.policy,
            "COMPOSITE_SUBJECT_POLICY_BINDING_MISMATCH",
        )
        _require(
            self.evaluation.universe_content_hash == subject.universe.content_hash,
            "COMPOSITE_SUBJECT_UNIVERSE_BINDING_MISMATCH",
        )
        _require(
            self.proposed_at >= self.evaluation.evaluated_at >= self.observations.source_generated_at,
            "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH",
        )
        _require(
            self.observations.source_generated_at[:10] > _month_window(subject.month)[1],
            "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH",
        )
        return self


class SubjectEvaluationApproval(HashedEligibilityWire):
    approved_at: Instant
    approved_by: Identifier
    claims_digest: Digest
    evidence_kind: Literal["SYNTHETIC_UNSIGNED", "QUALIFIED_VERIFICATION_RECEIPT"]
    membership_content_hash: Digest
    official_activation: Literal["UNAVAILABLE"]
    product_name: Literal["CompositeSubjectEvaluationApproval"]
    product_version: Literal["v1"]
    proposal: SubjectEvaluationProposal
    publication_posture: Literal["NOT_PUBLISHED"]
    universe_content_hash: Digest
    verification: VerificationReceipt

    @model_validator(mode="after")
    def approval_links(self) -> Self:
        _require(self.approved_by != self.proposal.proposed_by, "COMPOSITE_ELIGIBILITY_SELF_APPROVAL_FORBIDDEN")
        _require(self.approved_at >= self.proposal.proposed_at, "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH")
        _verification_subject(
            self.verification.request, self.proposal.policy_approval.proposal.subject, "ELIGIBILITY_POLICY_EVALUATION"
        )
        _require(
            self.verification.request.claims_digest == self.claims_digest, "COMPOSITE_VERIFICATION_CLAIMS_MISMATCH"
        )
        _require(
            self.verification.request.binding is None and self.verification.request.source_product is None,
            "COMPOSITE_VERIFICATION_BINDING_MISMATCH",
        )
        expected = "SYNTHETIC_NON_CERTIFYING" if self.evidence_kind == "SYNTHETIC_UNSIGNED" else "QUALIFIED_RECEIPT"
        _require(self.verification.posture == expected, "COMPOSITE_VERIFICATION_POSTURE_MISMATCH")
        return self


class SubjectFinalization(HashedEligibilityWire):
    definition: ManageCompositeDefinitionV2
    evaluation_approval: SubjectEvaluationApproval
    official_activation: Literal["UNAVAILABLE"]
    product_name: Literal["CompositeEligibilityFinalization"]
    product_version: Literal["v1"]
    subject: EligibilitySubject
    verifications: list[VerificationReceipt] = Field(min_length=3, max_length=258)

    @model_validator(mode="after")
    def finalization_links(self) -> Self:
        _require(
            self.subject == self.evaluation_approval.proposal.policy_approval.proposal.subject,
            "COMPOSITE_SUBJECT_FINALIZATION_SCOPE_MISMATCH",
        )
        _equal(
            self.subject,
            self.definition,
            _SCOPE
            + (
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
        _definition_links(self)
        _finalization_verifications(self)
        return self


class SubjectFinalizationReceipt(HashedEligibilityWire):
    completeness: Literal["UNVERIFIED"]
    finalization: SubjectFinalization
    membership_content_hash: Digest
    product_name: Literal["CompositeEligibilityFinalizationReceipt"]
    product_version: Literal["v1"]
    publication_sequence: Annotated[int, Field(ge=1)]
    universe_content_hash: Digest

    @model_validator(mode="after")
    def receipt_links(self) -> Self:
        _equal(
            self,
            self.finalization.evaluation_approval,
            ("membership_content_hash", "universe_content_hash"),
            "COMPOSITE_SUBJECT_PUBLICATION_HASH_MISMATCH",
        )
        return self


def _verification_subject(request: VerificationRequest, subject: EligibilitySubject, purpose: str) -> None:
    _equal(subject, request, _SCOPE, "COMPOSITE_VERIFICATION_SCOPE_MISMATCH")
    _require(request.purpose == purpose, "COMPOSITE_VERIFICATION_PURPOSE_MISMATCH")
    _require(request.subject_content_hash == subject.content_hash, "COMPOSITE_VERIFICATION_SUBJECT_MISMATCH")
    _require(
        (request.effective_from, request.effective_to) == _month_window(subject.month),
        "COMPOSITE_VERIFICATION_WINDOW_MISMATCH",
    )


def _observation_links(proposal: SubjectEvaluationProposal, subject: EligibilitySubject) -> None:
    observations, binding, evaluation = proposal.observations, proposal.observation_binding, proposal.evaluation
    digest = authority_digest(observations.model_dump())
    _require(
        (
            binding.authority_scope,
            binding.owner_service,
            binding.product_name,
            binding.contract_version,
            binding.source_cut_id,
            binding.source_watermark,
            binding.content_hash,
        )
        == (
            "POLICY_INPUT",
            subject.universe.observation_owner,
            observations.product_name,
            observations.product_version,
            observations.source_cut_id,
            observations.source_revision,
            digest,
        ),
        "COMPOSITE_SUBJECT_SOURCE_BINDING_MISMATCH",
    )
    _equal(
        observations,
        evaluation,
        ("source_cut_id", "source_revision", "evidence_class"),
        "COMPOSITE_SUBJECT_SOURCE_BINDING_MISMATCH",
    )
    _require(evaluation.input_content_hash == digest, "COMPOSITE_SUBJECT_SOURCE_BINDING_MISMATCH")


def _evaluation_members(proposal: SubjectEvaluationProposal, subject: EligibilitySubject) -> None:
    expected = [member.member_id for member in subject.universe.members]
    observations, evaluation = proposal.observations, proposal.evaluation
    _require(observations.expected_portfolio_ids == expected, "COMPOSITE_SUBJECT_MEMBER_MAP_MISMATCH")
    observed = [item.portfolio_id for item in observations.portfolios]
    _require(
        observed == sorted(set(observed)) and set(observed) <= set(expected), "COMPOSITE_SUBJECT_MEMBER_MAP_MISMATCH"
    )
    _require([item.portfolio_id for item in evaluation.portfolios] == expected, "COMPOSITE_SUBJECT_MEMBER_MAP_MISMATCH")
    _require(
        (evaluation.expected_count, evaluation.observed_count) == (len(expected), len(observed)),
        "COMPOSITE_SUBJECT_MEMBER_MAP_MISMATCH",
    )
    _require(
        all(item.currency == subject.reporting_currency for item in observations.portfolios),
        "COMPOSITE_SUBJECT_OBSERVATION_SCOPE_MISMATCH",
    )
    _evaluation_outcomes(evaluation, set(observed))


def _evaluation_outcomes(evaluation: MonthlyEligibilityEvaluation, observed: set[str]) -> None:
    counts = {
        status: sum(item.status == status for item in evaluation.portfolios)
        for status in ("INCLUDED", "EXCLUDED", "PENDING_REVIEW")
    }
    _require(
        (evaluation.included_count, evaluation.excluded_count, evaluation.pending_review_count)
        == (counts["INCLUDED"], counts["EXCLUDED"], counts["PENDING_REVIEW"]),
        "COMPOSITE_SUBJECT_DECISION_COUNT_MISMATCH",
    )
    for item in evaluation.portfolios:
        _require(item.observations_present == (item.portfolio_id in observed), "COMPOSITE_SUBJECT_MEMBER_MAP_MISMATCH")
        _require(
            {assessment.rule for assessment in item.assessments} == {"SIGNIFICANT_FLOW", "CASH", "READINESS"},
            "COMPOSITE_SUBJECT_RULE_SET_MISMATCH",
        )


def _definition_links(finalization: SubjectFinalization) -> None:
    definition, approval = finalization.definition, finalization.evaluation_approval
    profile = definition.source_authority
    binding = profile.payload.eligibility_evaluation_binding
    _require(
        binding
        == EvidenceBinding(
            product_name=approval.product_name,
            product_version=approval.product_version,
            revision=approval.proposal.evaluation_revision,
            digest=approval.content_hash,
        ),
        "COMPOSITE_SUBJECT_ELIGIBILITY_BINDING_MISMATCH",
    )
    _require(
        profile.payload.member_identities == finalization.subject.universe.members,
        "COMPOSITE_SUBJECT_MEMBER_MAP_MISMATCH",
    )
    _require(
        profile.profile_digest == authority_digest(profile.payload.model_dump()),
        "COMPOSITE_AUTHORITY_PROFILE_HASH_MISMATCH",
    )
    body = definition.model_dump(exclude={"authority_approval", "definition_payload_digest", "content_hash"})
    _require(
        definition.definition_payload_digest == authority_digest(body), "COMPOSITE_AUTHORITY_DEFINITION_HASH_MISMATCH"
    )
    _require(
        definition.content_hash == authority_digest(definition.model_dump(exclude={"content_hash"})),
        "COMPOSITE_AUTHORITY_CONTENT_HASH_MISMATCH",
    )
    _authority_claim_links(finalization)


def _authority_claim_links(finalization: SubjectFinalization) -> None:
    definition = finalization.definition
    payload = definition.source_authority.payload
    claims = definition.authority_approval.claims
    _equal(definition, claims, _SCOPE + ("definition_payload_digest",), "COMPOSITE_AUTHORITY_CLAIMS_BINDING_MISMATCH")
    _equal(
        payload,
        claims,
        ("profile_id", "profile_revision", "effective_from", "effective_to"),
        "COMPOSITE_AUTHORITY_CLAIMS_BINDING_MISMATCH",
    )
    _require(
        (claims.profile_digest, claims.eligibility_evidence_digest, claims.method_evidence_digest)
        == (
            definition.source_authority.profile_digest,
            payload.eligibility_evaluation_binding.digest,
            payload.return_method_binding.digest,
        ),
        "COMPOSITE_AUTHORITY_CLAIMS_BINDING_MISMATCH",
    )
    _require(claims.approving_identity != definition.created_by, "COMPOSITE_ELIGIBILITY_SELF_APPROVAL_FORBIDDEN")
    _require(claims.approved_at >= finalization.evaluation_approval.approved_at, "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH")


def _finalization_verifications(finalization: SubjectFinalization) -> None:
    requests = [receipt.request for receipt in finalization.verifications]
    _unique_verification_purposes(requests)
    for request in requests:
        _verification_subject(request, finalization.subject, request.purpose)
    _authority_verification(finalization.definition, requests)
    _method_verification(finalization.definition, requests)
    _provider_verifications(finalization.definition, requests)


def _unique_verification_purposes(requests: list[VerificationRequest]) -> None:
    keys = [
        (request.purpose, request.source_product, request.binding.model_dump_json() if request.binding else None)
        for request in requests
    ]
    _require(len(keys) == len(set(keys)), "COMPOSITE_VERIFICATION_DUPLICATE_PURPOSE")


def _authority_verification(definition: ManageCompositeDefinitionV2, requests: list[VerificationRequest]) -> None:
    authority = [request for request in requests if request.purpose == "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE"]
    _require(len(authority) == 1, "COMPOSITE_VERIFICATION_AUTHORITY_BINDING_MISMATCH")
    _require(
        (authority[0].binding, authority[0].source_product, authority[0].claims_digest)
        == (None, None, authority_digest(definition.authority_approval.claims.model_dump())),
        "COMPOSITE_VERIFICATION_AUTHORITY_BINDING_MISMATCH",
    )


def _method_verification(definition: ManageCompositeDefinitionV2, requests: list[VerificationRequest]) -> None:
    method = definition.source_authority.payload.return_method_binding
    methods = [request for request in requests if request.purpose == "RETURN_METHOD_CALENDAR"]
    _require(len(methods) == 1, "COMPOSITE_VERIFICATION_METHOD_BINDING_MISMATCH")
    _require(
        (methods[0].binding, methods[0].claims_digest, methods[0].source_product) == (method, method.digest, None),
        "COMPOSITE_VERIFICATION_METHOD_BINDING_MISMATCH",
    )


def _provider_verifications(definition: ManageCompositeDefinitionV2, requests: list[VerificationRequest]) -> None:
    profiles = definition.source_authority.payload
    providers = {provider.provider_id: provider for provider in profiles.providers}
    expected = set()
    for selection in profiles.selections:
        provider = providers[selection.provider_id]
        expected.add((selection.source_product, provider.registry_revision, provider.registry_digest))
    actual = set()
    for request in requests:
        if request.purpose == "PROVIDER_REGISTRATION" and request.binding is not None:
            _require(
                request.binding.product_name == "CompositeProviderRegistration",
                "COMPOSITE_VERIFICATION_PROVIDER_BINDING_MISMATCH",
            )
            actual.add((request.source_product, request.binding.revision, request.binding.digest))
    _require(
        actual == expected and len(requests) == len(expected) + 2, "COMPOSITE_VERIFICATION_PROVIDER_BINDING_MISMATCH"
    )


def decode_eligibility_receipt(wire: str) -> SubjectFinalizationReceipt | CompositeMonthlyEligibilityPublicationReceipt:
    """Decode exact wire strings; this is neither verification nor a custody join."""
    payload = decode_authority_json(wire)
    if payload.get("product_name") == "CompositeMonthlyEligibilityPublicationReceipt":
        from app.models.composite_monthly_eligibility_evidence import CompositeMonthlyEligibilityPublicationReceipt

        return CompositeMonthlyEligibilityPublicationReceipt.model_validate(payload)
    return SubjectFinalizationReceipt.model_validate(payload)
