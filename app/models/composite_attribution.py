"""Pinned single-period Composite attribution, in decimal return units."""

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, FiniteFloat, model_validator

from app.models.composite_authority import Digest, Identifier


def _observed_number(value):
    if isinstance(value, bool):
        raise ValueError("An observed financial number cannot be boolean.")
    return value


ObservedNumber = Annotated[FiniteFloat, BeforeValidator(_observed_number)]


class AttributionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompositeAttributionRequest(AttributionContract):
    calculation_id: UUID = Field(default_factory=uuid4)
    metric_id: Literal["SINGLE_PERIOD_BRINSON_FACHLER"] = "SINGLE_PERIOD_BRINSON_FACHLER"
    method: Literal["BRINSON_FACHLER_ARITHMETIC_THREE_EFFECT:v1"] = "BRINSON_FACHLER_ARITHMETIC_THREE_EFFECT:v1"
    composite_id: Identifier
    candidate_id: UUID
    source_manifest_id: Identifier
    policy_binding_id: Identifier
    period_start: date
    period_end: date
    reporting_currency: str = Field(pattern=r"^[A-Z]{3}$")
    return_view: Literal["GROSS", "NET_ACTUAL", "NET_MODEL_FEE"]
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = "FLOAT64"
    official_scope_id: Digest | None = None
    official_revision: int | None = Field(default=None, ge=1)
    correction_of_calculation_id: UUID | None = None

    @model_validator(mode="after")
    def explicit_scope(self):
        if self.period_end < self.period_start:
            raise ValueError("Attribution requires one forward explicit period.")
        if (self.official_scope_id is None) != (self.official_revision is None):
            raise ValueError("Official selection requires both scope and exact revision.")
        if self.correction_of_calculation_id == self.calculation_id:
            raise ValueError("A correction requires a new calculation identity.")
        return self


class AttributionSourcePin(AttributionContract):
    pin_id: Identifier
    owner: Identifier
    product_name: Identifier
    revision: Identifier
    source_cut_id: Identifier
    payload_digest: Digest
    coverage_from: date
    coverage_to: date
    page_ids: tuple[Identifier, ...]
    expected_page_count: int = Field(ge=1)
    omitted_component_count: int = Field(ge=0)
    completeness: Literal["COMPLETE", "INCOMPLETE", "UNAVAILABLE"]


class AttributionPolicy(AttributionContract):
    binding_id: Identifier
    revision: Identifier
    purpose: Literal["COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER"]
    aggregation: Literal["SOURCE_APPROVED_POOLED_COMPOSITE_GROUP_ECONOMICS"]
    method: Literal["BRINSON_FACHLER_ARITHMETIC_THREE_EFFECT:v1"]
    weight_basis: Literal["BEGINNING_CAPITAL"]
    return_basis: Literal["SINGLE_PERIOD_ARITHMETIC"]
    return_view: Literal["GROSS", "NET_ACTUAL", "NET_MODEL_FEE"]
    reporting_currency: str = Field(pattern=r"^[A-Z]{3}$")
    fee_basis: Identifier
    tax_basis: Identifier
    tolerance: FiniteFloat = Field(gt=0, le=1e-12)
    effective_from: date
    effective_to: date


class AttributionMember(AttributionContract):
    portfolio_id: Identifier
    status: Literal["INCLUDED", "EXCLUDED", "PENDING"]
    effective_from: date
    effective_to: date
    reason: Identifier
    composite_weight: ObservedNumber
    actual_return: ObservedNumber
    source_row_id: Identifier


class AttributionMemberGroup(AttributionContract):
    portfolio_id: Identifier
    group_id: Identifier
    member_weight: ObservedNumber
    actual_return: ObservedNumber
    source_row_id: Identifier


class AttributionGroup(AttributionContract):
    group_id: Identifier
    portfolio_weight: ObservedNumber
    benchmark_weight: ObservedNumber
    portfolio_return: ObservedNumber
    benchmark_return: ObservedNumber
    source_row_id: Identifier


class AttributionSourceBundle(AttributionContract):
    tenant_id: Identifier
    composite_id: Identifier
    source_manifest_id: Identifier
    candidate_id: UUID
    original_response_digest: Digest
    vector_digest: Digest
    period_start: date
    period_end: date
    reporting_currency: str = Field(pattern=r"^[A-Z]{3}$")
    return_view: Literal["GROSS", "NET_ACTUAL", "NET_MODEL_FEE"]
    membership_revision: Identifier
    membership_digest: Digest
    classification_revision: Identifier
    classification_pin_id: Identifier
    benchmark_id: Identifier
    benchmark_revision: Identifier
    benchmark_pin_id: Identifier
    group_source_pin_id: Identifier
    membership_pin_id: Identifier
    expected_portfolio_ids: tuple[Identifier, ...]
    expected_group_ids: tuple[Identifier, ...]
    expected_benchmark_group_ids: tuple[Identifier, ...]
    members: tuple[AttributionMember, ...]
    member_groups: tuple[AttributionMemberGroup, ...]
    groups: tuple[AttributionGroup, ...]
    source_pins: tuple[AttributionSourcePin, ...]
    compatible_pin_ids: tuple[Identifier, ...]
    compatibility_reference: Identifier
    policy: AttributionPolicy
    derivatives_present: bool
    qualification: Literal["CONTROLLED_SYNTHETIC_ONLY", "OWNER_QUALIFIED_SOURCE"]
    raw_source_bodies: dict[str, Any]


class AttributionApproval(AttributionContract):
    """Receipt returned by a configured verifier, never accepted from HTTP."""

    purpose: Literal["COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER"]
    bundle_digest: Digest
    policy_digest: Digest
    evidence_digest: Digest
    evidence_wire: str = Field(min_length=1, max_length=65536)
    canonical_maker: Identifier
    canonical_checker: Identifier
    qualification: Literal["SYNTHETIC_NON_CERTIFYING", "INSTITUTION_APPROVED"]


class AttributionObservation(AttributionContract):
    input_manifest_digest: Digest
    source_bundle: AttributionSourceBundle
    approval: AttributionApproval
    original_return: ObservedNumber
    portfolio_return: ObservedNumber
    benchmark_return: ObservedNumber
    portfolio_weight_sum: ObservedNumber
    benchmark_weight_sum: ObservedNumber
    portfolio_reconciliation_delta: ObservedNumber


class AttributionEffect(AttributionContract):
    group_id: Identifier
    allocation: ObservedNumber
    selection: ObservedNumber
    interaction: ObservedNumber
    total: ObservedNumber


class AttributionOutcome(AttributionContract):
    units: Literal["DECIMAL_RETURN"] = "DECIMAL_RETURN"
    precision_mode: Literal["FLOAT64"] = "FLOAT64"
    active_return_convention: Literal["ARITHMETIC_DIFFERENCE"] = "ARITHMETIC_DIFFERENCE"
    portfolio_return: ObservedNumber
    benchmark_return: ObservedNumber
    active_return: ObservedNumber
    allocation: ObservedNumber
    selection: ObservedNumber
    interaction: ObservedNumber
    reconciliation_delta: ObservedNumber
    groups: tuple[AttributionEffect, ...]


class CompositeAttributionResponse(AttributionContract):
    calculation_id: UUID
    composite_id: Identifier
    metric_id: Literal["SINGLE_PERIOD_BRINSON_FACHLER"] = "SINGLE_PERIOD_BRINSON_FACHLER"
    method: Literal["BRINSON_FACHLER_ARITHMETIC_THREE_EFFECT:v1"] = "BRINSON_FACHLER_ARITHMETIC_THREE_EFFECT:v1"
    qualification: Literal["CALCULATED_ANALYSIS"] = "CALCULATED_ANALYSIS"
    input_manifest_digest: Digest
    calculation_engine_version: str
    financial_input_fingerprint: str
    calculation_hash: str
    official_scope_id: Digest | None
    official_revision: int | None
    correction_of_calculation_id: UUID | None
    observation: AttributionObservation
    outcome: AttributionOutcome


class CompositeAttributionAcceptedResponse(AttributionContract):
    calculation_id: UUID
    status: Literal["accepted"] = "accepted"
    metric_id: Literal["SINGLE_PERIOD_BRINSON_FACHLER"] = "SINGLE_PERIOD_BRINSON_FACHLER"
    poll_path: str
    result_path: str
