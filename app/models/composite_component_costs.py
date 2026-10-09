"""Whole original gross-cost payloads; decoded identity is never supplier authority."""

from typing import Literal

from pydantic import Field, model_validator

from app.models.composite_authority import AuthorityWire, Digest, EvidenceBinding, Identifier, authority_digest
from app.models.composite_component_model_fees import CompositeGrossComponentEvidence
from app.models.composite_eligibility_evidence import VerificationReceipt
from app.models.composite_external_facts import DecimalWire
from app.models.composite_model_fees import model_fee_profile_json


class CompositeGrossCostMember(AuthorityWire):
    evidence: CompositeGrossComponentEvidence
    completeness: Literal["COMPLETE_COMPONENTS", "COMPLETE_ZERO"]
    reference_wealth_amount: DecimalWire
    reference_wealth_convention: Literal["BEGINNING_ASSETS_TIMES_GROSS_WEALTH_FACTOR"]

    @model_validator(mode="after")
    def complete_original_payload(self):
        if (self.completeness == "COMPLETE_ZERO") != (not self.evidence.included_components):
            raise ValueError("Empty gross component evidence requires explicit complete-zero declaration")
        reference = self.evidence.scope.reference_base
        reference_payload = {
            "gross_receipt_digest": self.evidence.scope.gross_receipt_digest,
            "reporting_currency": self.evidence.scope.reporting_currency,
            "reference_wealth_amount": self.reference_wealth_amount,
            "reference_wealth_convention": self.reference_wealth_convention,
        }
        if reference.product_name != "CompositePostGrossWealthReference" or reference.digest != authority_digest(
            reference_payload
        ):
            raise ValueError("Reference base binding must identify the original explicit common wealth denominator")
        binding = self.evidence.evidence_binding
        payload = self.model_dump(mode="json")
        del payload["evidence"]["evidence_binding"]
        if (binding.product_name, binding.product_version, binding.digest) != (
            "CompositeGrossComponentEvidence",
            "v1",
            authority_digest(payload),
        ):
            raise ValueError("Gross component binding must cover the whole original payload and nested hashes")
        return self


class CompositeGrossCostSource(AuthorityWire):
    product_name: Literal["CompositeGrossCostSource"]
    product_version: Literal["v1"]
    revision: Identifier
    producer_id: Identifier
    source_cut_id: Identifier
    source_watermark: Identifier
    definition_content_hash: Digest
    membership_content_hash: Digest
    attestation_content_hash: Digest
    model_fee_binding: EvidenceBinding
    members: list[CompositeGrossCostMember] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def bounded_complete_members(self):
        ids = [item.evidence.scope.member_id for item in self.members]
        if ids != sorted(set(ids)):
            raise ValueError("Gross-cost source requires sorted unique complete member identities")
        model_fee_profile_json(self.model_dump(mode="json"))
        return self


class CompositeGrossCostReceipt(AuthorityWire):
    source: CompositeGrossCostSource
    verification: VerificationReceipt
