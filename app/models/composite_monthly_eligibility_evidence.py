"""Exact recurring Manage evidence; decoding never supplies independent trust.

Legacy unmarked proposals retain their original wire/hash. A publication receipt
requires the new server-owned version marker and binds the full approval digest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_serializer, model_validator

from app.models.composite_authority import (
    BusinessDate,
    Digest,
    EvidenceBinding,
    Identifier,
    Instant,
    ManageCompositeDefinitionV2,
    authority_digest,
    legacy_composite_product_digest,
)
from app.models.composite_eligibility_evidence import (
    DpmCompositeUniverseSourceProduct,
    EligibilityWire,
    HashedEligibilityWire,
    MonthlyEligibilityEvaluation,
    MonthlyEligibilityObservations,
    MonthlyPolicyApproval,
    VerifiedMonthlySourceAssembly,
    _equal,
    _evaluation_outcomes,
    _month_window,
    _require,
    retained_monthly_source_assembly,
)

_SCOPE = ("tenant_id", "composite_id", "definition_version")


def monthly_publication_binding(products: list[dict[str, Any]], source_cut_id: str) -> EvidenceBinding | None:
    """Select the current locator; malformed duplicates cannot trigger first-month fallback."""
    locators = [item for item in products if item.get("product_name") == "CompositeMonthlyEvaluationApproval"]
    if not locators:
        return None
    _require(len(locators) == 1, "COMPOSITE_MONTHLY_APPROVAL_LOCATOR_MISMATCH")
    locator = DpmCompositeUniverseSourceProduct.model_validate(locators[0])
    _require(
        (locator.owner_service, locator.authority_scope, locator.source_cut_id)
        == ("lotus-manage", "POLICY_INPUT", source_cut_id),
        "COMPOSITE_MONTHLY_APPROVAL_LOCATOR_MISMATCH",
    )
    return EvidenceBinding(
        product_name=locator.product_name,
        product_version=locator.contract_version,
        revision=locator.source_watermark,
        digest=locator.content_hash,
    )


class MonthlyEvaluationUniverse(EligibilityWire):
    """Retained parent membership universe using the unchanged v1 hash contract."""

    product_name: Literal["CompositeUniverseAttestation"]
    product_version: Literal["v1"]
    tenant_id: Identifier
    composite_id: Identifier
    definition_version: Identifier
    membership_revision: Identifier
    membership_content_hash: Digest
    attestation_version: Identifier
    coverage_from: BusinessDate
    coverage_to: BusinessDate
    policy_version: Identifier
    source_cut_id: Identifier
    source_products: list[DpmCompositeUniverseSourceProduct] = Field(min_length=1, max_length=20)
    posture: Literal["COMPLETE", "INCOMPLETE", "UNAVAILABLE"]
    expected_portfolio_ids: list[Identifier] = Field(max_length=1000)
    expected_portfolio_count: Annotated[int, Field(ge=0, le=1000)]
    observed_portfolio_count: Annotated[int, Field(ge=0, le=1000)]
    missing_portfolio_ids: list[Identifier] = Field(max_length=1000)
    unexpected_portfolio_ids: list[Identifier] = Field(max_length=1000)
    coverage_gap_portfolio_ids: list[Identifier] = Field(max_length=1000)
    reason_code: str | None
    # The v1 producer emits ISO UTC with or without fractional seconds. Preserve
    # the exact lexical wire before hashing instead of normalizing a datetime.
    attested_at: str
    attested_by: Identifier
    correlation_id: Identifier
    content_hash: Digest

    @field_validator("attested_at")
    @classmethod
    def aware_attestation_time(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        _require(parsed.utcoffset() is not None, "COMPOSITE_MONTHLY_ATTESTATION_TIME_INVALID")
        return value

    @model_validator(mode="after")
    def universe_links(self) -> Self:
        _require(
            legacy_composite_product_digest(self.model_dump()) == self.content_hash,
            "COMPOSITE_MONTHLY_UNIVERSE_HASH_MISMATCH",
        )
        _require(self.coverage_from <= self.coverage_to, "COMPOSITE_MONTHLY_WINDOW_MISMATCH")
        for ids in (
            self.expected_portfolio_ids,
            self.missing_portfolio_ids,
            self.unexpected_portfolio_ids,
            self.coverage_gap_portfolio_ids,
        ):
            _require(ids == sorted(set(ids)), "COMPOSITE_MONTHLY_UNIVERSE_NONCANONICAL")
        _require(
            self.expected_portfolio_count == len(self.expected_portfolio_ids),
            "COMPOSITE_MONTHLY_UNIVERSE_COUNT_MISMATCH",
        )
        keys = [
            (item.owner_service, item.product_name, item.contract_version, item.source_cut_id)
            for item in self.source_products
        ]
        _require(keys == sorted(set(keys)), "COMPOSITE_MONTHLY_SOURCE_PRODUCTS_NONCANONICAL")
        _require(
            sum(item.authority_scope == "AUTHORITATIVE_UNIVERSE" for item in self.source_products) == 1,
            "COMPOSITE_MONTHLY_REGISTRY_BINDING_MISMATCH",
        )
        _complete_universe(self)
        return self


def _complete_universe(universe: MonthlyEvaluationUniverse) -> None:
    if universe.posture == "COMPLETE":
        _require(
            universe.expected_portfolio_count > 0
            and universe.observed_portfolio_count == universe.expected_portfolio_count
            and not universe.missing_portfolio_ids
            and not universe.unexpected_portfolio_ids
            and not universe.coverage_gap_portfolio_ids
            and universe.reason_code is None,
            "COMPOSITE_MONTHLY_UNIVERSE_INCOMPLETE",
        )


class MonthlyEvaluationProposal(HashedEligibilityWire):
    """One independently policy-approved month and its pinned observations/evaluation."""

    product_name: Literal["CompositeMonthlyEvaluationProposal"]
    product_version: Literal["v1"]
    evaluation_revision: Identifier
    target_membership_revision: Identifier
    parent_membership_revision: Identifier
    parent_membership_content_hash: Digest
    policy_approval: MonthlyPolicyApproval
    universe: MonthlyEvaluationUniverse
    observations: MonthlyEligibilityObservations
    source_assembly_evidence: VerifiedMonthlySourceAssembly | None = None
    publication_evidence_version: Literal["v1"] | None = None
    evaluation: MonthlyEligibilityEvaluation
    proposed_by: Identifier
    proposed_at: Instant
    correlation_id: Identifier

    @model_serializer(mode="wrap")
    def legacy_optional_fields(self, handler: Any) -> dict[str, Any]:
        payload: dict[str, Any] = handler(self)
        for field in ("source_assembly_evidence", "publication_evidence_version"):
            if getattr(self, field) is None:
                payload.pop(field, None)
        return payload

    @model_validator(mode="before")
    @classmethod
    def canonical_optional_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for field in ("source_assembly_evidence", "publication_evidence_version"):
                _require(field not in value or value[field] is not None, "COMPOSITE_MONTHLY_NONCANONICAL_NULL")
        return value

    @model_validator(mode="after")
    def proposal_links(self) -> Self:
        # Revalidate mutable nested instances as well as ordinary decoded JSON.
        self.policy_approval = MonthlyPolicyApproval.model_validate(self.policy_approval.model_dump())
        self.universe = MonthlyEvaluationUniverse.model_validate(self.universe.model_dump())
        self.observations = MonthlyEligibilityObservations.model_validate(self.observations.model_dump())
        self.evaluation = MonthlyEligibilityEvaluation.model_validate(self.evaluation.model_dump())
        self.source_assembly_evidence = retained_monthly_source_assembly(
            self.source_assembly_evidence, self.observations
        )
        _monthly_policy_links(self)
        _monthly_source_links(self)
        _monthly_evaluation_links(self)
        _require(
            self.target_membership_revision != self.parent_membership_revision,
            "COMPOSITE_MONTHLY_TARGET_REVISION_REUSED",
        )
        return self


def _monthly_policy_links(proposal: MonthlyEvaluationProposal) -> None:
    approval = proposal.policy_approval
    policy = approval.proposal.policy
    first, last = _month_window(policy.month)
    _equal(policy.scope, proposal.universe, _SCOPE, "COMPOSITE_MONTHLY_SCOPE_MISMATCH")
    _require(
        proposal.universe.coverage_from <= first <= last <= proposal.universe.coverage_to,
        "COMPOSITE_MONTHLY_WINDOW_MISMATCH",
    )
    _require(
        proposal.universe.policy_version == approval.proposal.eligibility_policy_version,
        "COMPOSITE_MONTHLY_POLICY_BINDING_MISMATCH",
    )
    _require(
        approval.approved_by != approval.proposal.proposed_by,
        "COMPOSITE_ELIGIBILITY_SELF_APPROVAL_FORBIDDEN",
    )
    _require(
        approval.proposal.proposed_at <= approval.approved_at,
        "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH",
    )
    _require(approval.approved_at[:10] < first, "COMPOSITE_ELIGIBILITY_POLICY_NOT_PROSPECTIVE")
    attachments = [(item.product_name, item.product_version, item.revision) for item in approval.proposal.attachments]
    _require(attachments == sorted(set(attachments)), "COMPOSITE_MONTHLY_ATTACHMENTS_NONCANONICAL")


def _monthly_source_links(proposal: MonthlyEvaluationProposal) -> None:
    observations = proposal.observations
    universe = proposal.universe
    _equal(observations, universe, _SCOPE, "COMPOSITE_MONTHLY_SCOPE_MISMATCH")
    _require(
        (universe.membership_revision, universe.membership_content_hash)
        == (proposal.parent_membership_revision, proposal.parent_membership_content_hash),
        "COMPOSITE_MONTHLY_PARENT_BINDING_MISMATCH",
    )
    _require(
        observations.expected_portfolio_ids == universe.expected_portfolio_ids,
        "COMPOSITE_MONTHLY_MEMBER_MAP_MISMATCH",
    )
    products = [
        item
        for item in universe.source_products
        if item.product_name == observations.product_name
        and item.contract_version == observations.product_version
        and item.authority_scope == "POLICY_INPUT"
    ]
    _require(len(products) == 1, "COMPOSITE_MONTHLY_SOURCE_REFERENCE_UNAVAILABLE")
    _require(
        (products[0].source_cut_id, products[0].source_watermark, products[0].content_hash)
        == (observations.source_cut_id, observations.source_revision, authority_digest(observations.model_dump())),
        "COMPOSITE_MONTHLY_SOURCE_BINDING_MISMATCH",
    )


def _monthly_evaluation_links(proposal: MonthlyEvaluationProposal) -> None:
    observations, evaluation = proposal.observations, proposal.evaluation
    policy = proposal.policy_approval.proposal.policy
    _equal(
        observations,
        evaluation,
        _SCOPE + ("month", "source_cut_id", "source_revision", "evidence_class"),
        "COMPOSITE_MONTHLY_EVALUATION_BINDING_MISMATCH",
    )
    _require(
        observations.month == policy.month and evaluation.resolved_policy == policy,
        "COMPOSITE_MONTHLY_POLICY_BINDING_MISMATCH",
    )
    _require(
        evaluation.input_content_hash == authority_digest(observations.model_dump())
        and evaluation.universe_content_hash == proposal.universe.content_hash,
        "COMPOSITE_MONTHLY_EVALUATION_BINDING_MISMATCH",
    )
    _require(
        proposal.proposed_at == evaluation.evaluated_at >= observations.source_generated_at
        and observations.source_generated_at[:10] > _month_window(observations.month)[1],
        "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH",
    )
    _monthly_evaluation_population(proposal)


def _monthly_evaluation_population(proposal: MonthlyEvaluationProposal) -> None:
    observations, evaluation = proposal.observations, proposal.evaluation
    expected = observations.expected_portfolio_ids
    observed = [item.portfolio_id for item in observations.portfolios]
    _require(
        observed == sorted(set(observed)) and set(observed) <= set(expected), "COMPOSITE_MONTHLY_MEMBER_MAP_MISMATCH"
    )
    _require(
        [item.portfolio_id for item in evaluation.portfolios] == expected
        and (evaluation.expected_count, evaluation.observed_count) == (len(expected), len(observed)),
        "COMPOSITE_MONTHLY_MEMBER_MAP_MISMATCH",
    )
    _require(
        all(item.currency == observations.reporting_currency for item in observations.portfolios),
        "COMPOSITE_MONTHLY_CURRENCY_MISMATCH",
    )
    _evaluation_outcomes(evaluation, set(observed))
    _monthly_evaluation_statuses(evaluation)
    coverage = "COMPLETE" if len(expected) == len(observed) else "INCOMPLETE"
    _require(evaluation.declared_universe_coverage == coverage, "COMPOSITE_MONTHLY_COVERAGE_MISMATCH")


def _monthly_evaluation_statuses(evaluation: MonthlyEligibilityEvaluation) -> None:
    for item in evaluation.portfolios:
        outcomes = [assessment.outcome for assessment in item.assessments]
        status = "EXCLUDED" if "FAIL" in outcomes else "PENDING_REVIEW" if "UNKNOWN" in outcomes else "INCLUDED"
        _require(item.status == status, "COMPOSITE_MONTHLY_STATUS_MISMATCH")


class MonthlyEvaluationApproval(HashedEligibilityWire):
    """Unsigned independent checker claims; verification remains a server responsibility."""

    product_name: Literal["CompositeMonthlyEvaluationApproval"]
    product_version: Literal["v1"]
    evidence_kind: Literal["SYNTHETIC_UNSIGNED"]
    official_activation: Literal["UNAVAILABLE"]
    proposal: MonthlyEvaluationProposal
    approved_by: Identifier
    approved_at: Instant
    claims_digest: Digest
    membership_content_hash: Digest
    published_universe_content_hash: Digest

    @model_validator(mode="after")
    def approval_links(self) -> Self:
        self.proposal = MonthlyEvaluationProposal.model_validate(self.proposal.model_dump())
        _require(self.approved_by != self.proposal.proposed_by, "COMPOSITE_ELIGIBILITY_SELF_APPROVAL_FORBIDDEN")
        _require(self.approved_at >= self.proposal.proposed_at, "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH")
        _require(
            self.claims_digest
            == authority_digest(
                {
                    "purpose": "COMPOSITE_MONTHLY_MEMBERSHIP_APPROVAL",
                    "proposal_content_hash": self.proposal.content_hash,
                    "approved_by": self.approved_by,
                    "approved_at": self.approved_at,
                }
            ),
            "COMPOSITE_MONTHLY_APPROVAL_CLAIMS_MISMATCH",
        )
        return self


class CompositeMonthlyEligibilityPublicationReceipt(HashedEligibilityWire):
    """Published join pins with every nested hash retained in the root self-hash."""

    product_name: Literal["CompositeMonthlyEligibilityPublicationReceipt"]
    product_version: Literal["v1"]
    definition: ManageCompositeDefinitionV2
    approval: MonthlyEvaluationApproval
    membership_binding: EvidenceBinding
    universe_binding: EvidenceBinding
    source_cut_id: Identifier
    publication_sequence: Annotated[int, Field(ge=1)]
    completeness: Literal["UNVERIFIED"]

    @model_validator(mode="after")
    def publication_links(self) -> Self:
        self.definition = ManageCompositeDefinitionV2.model_validate(self.definition.model_dump())
        self.approval = MonthlyEvaluationApproval.model_validate(self.approval.model_dump())
        proposal = self.approval.proposal
        _require(proposal.publication_evidence_version == "v1", "COMPOSITE_MONTHLY_PUBLICATION_VERSION_UNAVAILABLE")
        _require(proposal.source_assembly_evidence is not None, "COMPOSITE_MONTHLY_SOURCE_ASSEMBLY_UNAVAILABLE")
        _equal(
            self.definition,
            proposal.policy_approval.proposal.policy.scope,
            _SCOPE + ("strategy_code",),
            "COMPOSITE_MONTHLY_SCOPE_MISMATCH",
        )
        _require(
            self.definition.eligibility_policy_version == proposal.policy_approval.proposal.eligibility_policy_version
            and self.definition.reporting_currency == proposal.observations.reporting_currency,
            "COMPOSITE_MONTHLY_POLICY_BINDING_MISMATCH",
        )
        _require(
            [item.member_id for item in self.definition.source_authority.payload.member_identities]
            == proposal.observations.expected_portfolio_ids,
            "COMPOSITE_MONTHLY_MEMBER_MAP_MISMATCH",
        )
        _require(self.source_cut_id == proposal.universe.source_cut_id, "COMPOSITE_MONTHLY_SOURCE_CUT_MISMATCH")
        _require(
            self.membership_binding
            == EvidenceBinding(
                product_name="CompositeMembership",
                product_version="v1",
                revision=proposal.target_membership_revision,
                digest=self.approval.membership_content_hash,
            ),
            "COMPOSITE_MONTHLY_MEMBERSHIP_BINDING_MISMATCH",
        )
        _require(
            self.universe_binding
            == EvidenceBinding(
                product_name="CompositeUniverseAttestation",
                product_version="v1",
                revision=proposal.evaluation_revision,
                digest=self.approval.published_universe_content_hash,
            ),
            "COMPOSITE_MONTHLY_UNIVERSE_BINDING_MISMATCH",
        )
        return self
