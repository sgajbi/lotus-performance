"""Consumer projection of Manage's immutable CompositeDefinition:v2 wire.

No resolver, caller assertion or profile digest is institutional trust.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Digest = Annotated[str, Field(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")]
BusinessDate = Annotated[str, Field(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}$")]
Instant = Annotated[str, Field(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")]


def authority_digest(payload: dict[str, Any]) -> str:
    """Hash an explicit payload; retain all nested digests and approval fields."""
    wire = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return "sha256:" + hashlib.sha256(wire.encode("utf-8")).hexdigest()


def legacy_composite_product_digest(payload: dict[str, Any]) -> str:
    """Preserve Manage v1 membership/universe hashing, including nested omissions.

    Nested source-product digests must also be compared independently at admission.
    This historical algorithm is not the full-envelope approval/receipt algorithm.
    """

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items() if key != "content_hash"}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    return authority_digest(strip(payload))


def decode_authority_json(wire: str) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate authority JSON key")
            result[key] = value
        return result

    def invalid_number(value):
        raise ValueError("Authority JSON floats and nonfinite numbers are forbidden")

    payload = json.loads(wire, object_pairs_hook=pairs, parse_float=invalid_number, parse_constant=invalid_number)
    if not isinstance(payload, dict):
        raise ValueError("Authority JSON must be an object")
    return payload


class AuthorityWire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceBinding(AuthorityWire):
    product_name: Identifier
    product_version: Literal["v1"]
    revision: Identifier
    digest: Digest


class MemberIdentity(AuthorityWire):
    identity_kind: Literal["CORE_PORTFOLIO", "EXTERNAL_MEMBER"]
    member_id: Identifier
    namespace: Identifier
    provider_id: Identifier
    source_member_id: Identifier


class AuthorityProvider(AuthorityWire):
    provider_id: Identifier
    source_kind: Literal["LOTUS_CORE", "LOTUS_PERFORMANCE", "EXTERNAL_PROVIDER"]
    registry_revision: Identifier
    registry_digest: Digest
    trust_registration_ref: Identifier


class AuthoritySelection(AuthorityWire):
    selection_id: Identifier
    fact: Literal["MEMBER_RETURN", "BEGINNING_ASSETS", "ENDING_ASSETS", "BENCHMARK_RETURN"]
    member_ids: list[Identifier] = Field(min_length=1, max_length=1000)
    effective_from: BusinessDate
    effective_to: BusinessDate
    provider_id: Identifier
    economic_authority: Identifier
    publisher_service: Identifier
    source_product: Identifier
    source_contract_version: Identifier
    source_revision: Identifier
    source_watermark: Identifier
    source_cut_id: Identifier
    source_digest: Digest
    method_profile_binding: EvidenceBinding | None

    @model_validator(mode="after")
    def valid_window(self) -> AuthoritySelection:
        if date.fromisoformat(self.effective_to) < date.fromisoformat(self.effective_from):
            raise ValueError("Authority interval is inverted")
        if self.member_ids != sorted(set(self.member_ids)):
            raise ValueError("Selection members must be sorted and unique")
        return self


class CompositeAuthorityPayload(AuthorityWire):
    product_name: Literal["CompositeSourceAuthority"]
    product_version: Literal["v2"]
    profile_id: Identifier
    profile_revision: Identifier
    tenant_id: Identifier
    composite_id: Identifier
    effective_from: BusinessDate
    effective_to: BusinessDate
    mode: Literal["INTERNAL", "EXTERNAL", "HYBRID"]
    definition_owner: Literal["lotus-manage"]
    membership_owner: Literal["lotus-manage"]
    publisher: Literal["lotus-manage"]
    materialization_owner: Literal["lotus-performance"]
    calculation_owner: Literal["lotus-performance"]
    member_identities: list[MemberIdentity] = Field(min_length=1, max_length=1000)
    providers: list[AuthorityProvider] = Field(min_length=1, max_length=16)
    selections: list[AuthoritySelection] = Field(min_length=2, max_length=256)
    eligibility_evaluation_binding: EvidenceBinding
    return_method_binding: EvidenceBinding

    @model_validator(mode="after")
    def canonical_collections(self) -> CompositeAuthorityPayload:
        if date.fromisoformat(self.effective_to) < date.fromisoformat(self.effective_from):
            raise ValueError("Profile interval is inverted")
        for values, key in (
            (self.member_identities, "member_id"),
            (self.providers, "provider_id"),
            (self.selections, "selection_id"),
        ):
            ids = [getattr(value, key) for value in values]
            if ids != sorted(set(ids)):
                raise ValueError("Authority identities must be sorted and unique")
        return self


class CompositeAuthorityProfile(AuthorityWire):
    payload: CompositeAuthorityPayload
    profile_digest: Digest


class AuthorityApprovalClaims(AuthorityWire):
    purpose: Literal["COMPOSITE_ECONOMIC_AUTHORITY_PROFILE"]
    schema_version: Literal["synthetic-approval-claims.v1", "composite-authority-approval-claims.v1"]
    tenant_id: Identifier
    composite_id: Identifier
    definition_version: Identifier
    profile_id: Identifier
    profile_revision: Identifier
    profile_digest: Digest
    definition_payload_digest: Digest
    effective_from: BusinessDate
    effective_to: BusinessDate
    eligibility_evidence_digest: Digest
    method_evidence_digest: Digest
    approving_identity: Identifier
    approved_at: Instant


class SyntheticApprovalClaims(AuthorityApprovalClaims):
    schema_version: Literal["synthetic-approval-claims.v1"]


class SyntheticAuthorityApproval(AuthorityWire):
    """Decode the agreed engineering wire without granting official activation."""

    evidence_kind: Literal["SYNTHETIC_UNSIGNED"]
    claims: SyntheticApprovalClaims
    official_activation: Literal["UNAVAILABLE"]


class InstitutionalApprovalClaims(AuthorityApprovalClaims):
    schema_version: Literal["composite-authority-approval-claims.v1"]


class InstitutionalAttestationReference(AuthorityWire):
    contract_version: Literal["composite-authority-attestation.v1"]
    issuer_id: Identifier
    attestation_id: Identifier
    revision: Identifier
    digest: Digest


class InstitutionalAuthorityApproval(AuthorityWire):
    evidence_kind: Literal["INSTITUTIONAL_ATTESTATION_REFERENCE"]
    claims: InstitutionalApprovalClaims
    attestation: InstitutionalAttestationReference
    official_activation: Literal["UNAVAILABLE"]


class ManageCompositeDefinitionV2(AuthorityWire):
    product_name: Literal["CompositeDefinition"]
    product_version: Literal["v2"]
    tenant_id: Identifier
    composite_id: Identifier
    definition_version: Identifier
    display_name: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    strategy_code: Identifier
    reporting_currency: Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}$")]
    inception_date: BusinessDate
    termination_date: BusinessDate | None
    calculation_method: Literal["ASSET_WEIGHTED"]
    eligibility_policy_version: Identifier
    source_authority: CompositeAuthorityProfile
    created_at: Instant
    created_by: Identifier
    correlation_id: Identifier
    definition_payload_digest: Digest
    authority_approval: Annotated[
        SyntheticAuthorityApproval | InstitutionalAuthorityApproval, Field(discriminator="evidence_kind")
    ]
    content_hash: Digest

    @model_validator(mode="after")
    def canonical_dates(self) -> ManageCompositeDefinitionV2:
        start = date.fromisoformat(self.inception_date)
        if self.termination_date is not None and date.fromisoformat(self.termination_date) < start:
            raise ValueError("Definition interval is inverted")
        datetime.strptime(self.created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
        datetime.strptime(self.authority_approval.claims.approved_at, "%Y-%m-%dT%H:%M:%S.%fZ")
        return self

    def performance_definition(self):
        from app.models.composites import CompositeDefinition

        return CompositeDefinition.model_validate(
            self.model_dump(
                include={
                    "composite_id",
                    "display_name",
                    "strategy_code",
                    "reporting_currency",
                    "inception_date",
                    "termination_date",
                    "calculation_method",
                    "source_authority",
                }
            )
        )
