"""Explicit periodic component allocation; parsing never confers method approval."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.models.composite_authority import AuthorityWire, BusinessDate, Digest, EvidenceBinding, Identifier
from app.models.composite_currency_normalization import Currency
from app.models.composite_external_facts import DecimalWire
from app.models.composite_model_fees import (
    model_fee_profile_json,
    require_model_fee_calendar_coverage,
    require_unique_model_fee_entries,
)

ComponentCostCategory = Literal["TRANSACTION_COST", "MANAGEMENT_ADVISORY_FEE", "CUSTODY_FEE", "ADMINISTRATION_FEE"]


def _require_fraction(value):
    if not Decimal(0) <= Decimal(value) < Decimal(1):
        raise ValueError("Component period wealth fractions must be zero-inclusive and one-exclusive")


def _require_unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f"Component model fee requires unique {label}")


class CompositeModelFeeComponent(AuthorityWire):
    component_id: Identifier
    economic_charge_id: Identifier
    category: ComponentCostCategory
    period_fee_fraction: DecimalWire
    reference_base: EvidenceBinding
    allocation_evidence: EvidenceBinding
    treatment: Literal["DEDUCT", "ALREADY_INCLUDED_IN_GROSS"]
    gross_inclusion_evidence: EvidenceBinding | None

    @model_validator(mode="after")
    def supported_fraction(self):
        _require_fraction(self.period_fee_fraction)
        if (self.treatment == "ALREADY_INCLUDED_IN_GROSS") != (self.gross_inclusion_evidence is not None):
            raise ValueError("Only an explicit already-included component requires pinned gross inclusion evidence")
        return self


class CompositeModelFeeBundle(AuthorityWire):
    bundle_id: Identifier
    component_ids: list[Identifier] = Field(min_length=1, max_length=64)
    declared_period_fee_fraction: DecimalWire
    allocation_evidence: EvidenceBinding

    @model_validator(mode="after")
    def explicit_allocation(self):
        _require_fraction(self.declared_period_fee_fraction)
        if self.component_ids != sorted(set(self.component_ids)):
            raise ValueError("Bundle component identifiers must be explicitly sorted and unique")
        return self


def _require_container_partition(components, bundles):
    component_ids = {row.component_id for row in components}
    bundle_ids = [row.bundle_id for row in bundles]
    _require_unique(bundle_ids, "bundle identities")
    allocated = [component_id for bundle in bundles for component_id in bundle.component_ids]
    _require_unique(allocated, "component allocation across containers")
    if set(bundle_ids) & component_ids or not set(allocated) <= component_ids:
        raise ValueError("A bundle is a container, never a component charge or unknown allocation")


class CompositeComponentMemberFee(AuthorityWire):
    entry_id: Identifier
    member_id: Identifier
    gross_receipt_digest: Digest
    gross_component_evidence_binding: EvidenceBinding
    reference_base: EvidenceBinding
    components: list[CompositeModelFeeComponent] = Field(min_length=1, max_length=64)
    bundles: list[CompositeModelFeeBundle] = Field(max_length=16)

    @model_validator(mode="after")
    def distinct_component_economics(self):
        _require_unique([row.component_id for row in self.components], "component identities")
        _require_unique([row.economic_charge_id for row in self.components], "economic-charge identities")
        _require_container_partition(self.components, self.bundles)
        return self


class CompositeComponentFeePeriod(AuthorityWire):
    period_start: BusinessDate
    period_end: BusinessDate
    member_rates: list[CompositeComponentMemberFee] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def ordered_members(self):
        if date.fromisoformat(self.period_end) < date.fromisoformat(self.period_start):
            raise ValueError("Component model-fee period is inverted")
        members = [row.member_id for row in self.member_rates]
        if members != sorted(set(members)):
            raise ValueError("Component model-fee members must be sorted and unique")
        return self


def _require_entry_containers(context, entry):
    allocated = {item for bundle in entry.bundles for item in bundle.component_ids}
    if context == "UNBUNDLED":
        if entry.bundles:
            raise ValueError("Unbundled presentation cannot carry fee containers")
    elif allocated != {row.component_id for row in entry.components}:
        raise ValueError("Bundled presentation requires complete explicit component allocation")


def _require_presentation_containers(context, periods):
    for period in periods:
        for entry in period.member_rates:
            _require_entry_containers(context, entry)


class CompositeComponentModelFeeProfile(AuthorityWire):
    product_name: Literal["CompositeComponentPeriodicModelFeeProfile"]
    product_version: Literal["v1"]
    profile_id: Identifier
    revision: Identifier
    tenant_id: Identifier
    composite_id: Identifier
    method_binding: EvidenceBinding
    calendar_binding: EvidenceBinding
    effective_from: BusinessDate
    effective_to: BusinessDate
    reporting_currency: Currency
    gross_source_basis: Literal["GROSS"]
    reference_base_basis: Literal["COMMON_POST_GROSS_WEALTH"]
    rate_basis: Literal["EXPLICIT_ALLOCATED_PERIOD_WEALTH_FRACTIONS"]
    bundled_fee_context: Literal["UNBUNDLED", "BUNDLED", "WRAP"]
    timing: Literal["END_OF_COMPLETE_PERIOD_AFTER_GROSS_RETURN"]
    transformation: Literal["MULTIPLICATIVE_WEALTH_HAIRCUT"]
    asset_treatment: Literal["UNCHANGED_SOURCE_ASSETS_BEGINNING_ASSET_WEIGHTING"]
    monetary_precision: Literal["DECIMAL_STRICT_NO_INTERMEDIATE_ROUNDING"]
    standards_applicability: Literal["NOT_ASSESSED_ENGINEERING_METHOD_ONLY"]
    periods: list[CompositeComponentFeePeriod] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def complete_profile(self):
        require_model_fee_calendar_coverage(
            self.effective_from, self.effective_to, [(row.period_start, row.period_end) for row in self.periods]
        )
        require_unique_model_fee_entries([entry.entry_id for period in self.periods for entry in period.member_rates])
        _require_presentation_containers(self.bundled_fee_context, self.periods)
        model_fee_profile_json(self.model_dump(mode="json"))
        return self


class CompositeGrossComponentScope(AuthorityWire):
    tenant_id: Identifier
    composite_id: Identifier
    member_id: Identifier
    period_start: BusinessDate
    period_end: BusinessDate
    reporting_currency: Currency
    method_binding: EvidenceBinding
    calendar_binding: EvidenceBinding
    gross_receipt_digest: Digest
    reference_base: EvidenceBinding


class CompositeGrossIncludedComponent(AuthorityWire):
    component_id: Identifier
    economic_charge_id: Identifier
    category: ComponentCostCategory
    period_fee_fraction: DecimalWire
    reference_base: EvidenceBinding
    source_evidence: EvidenceBinding

    @model_validator(mode="after")
    def supported_fraction(self):
        _require_fraction(self.period_fee_fraction)
        return self


class CompositeGrossComponentEvidence(AuthorityWire):
    scope: CompositeGrossComponentScope
    evidence_binding: EvidenceBinding
    included_components: list[CompositeGrossIncludedComponent] = Field(max_length=64)

    @model_validator(mode="after")
    def distinct_original_charges(self):
        _require_unique([row.component_id for row in self.included_components], "included component identities")
        _require_unique([row.economic_charge_id for row in self.included_components], "included economic charges")
        return self
