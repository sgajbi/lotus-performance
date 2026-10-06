"""Consume Manage's immutable v1 products without manufacturing source authority.

Wire digests follow Manage's canonical JSON contract at 58656c9e. Validate the raw
wire payload before typed projection so timestamp spelling is not rewritten.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.composite_authority import ManageCompositeDefinitionV2, authority_digest
from app.models.composite_materialization import CompositeMaterializationCommand
from app.models.composites import CompositeDefinition, CompositeMembership, CompositeSourceAuthority
from app.services.composite_materialization.authority_policy import admit_authority_profile
from core.errors import APIUnprocessableEntityError


def source_refusal(code: str) -> APIUnprocessableEntityError:
    return APIUnprocessableEntityError(detail="Pinned composite source evidence failed admission.", error_code=code)


def _without_content_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_content_hash(item) for key, item in value.items() if key != "content_hash"}
    if isinstance(value, list):
        return [_without_content_hash(item) for item in value]
    return value


def source_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(_without_content_hash(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _ManageIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_version: Literal["v1"]
    tenant_id: str
    composite_id: str
    definition_version: str
    content_hash: str


class ManageCompositeDefinition(_ManageIdentity):
    product_name: Literal["CompositeDefinition"]
    display_name: str
    strategy_code: str
    reporting_currency: str
    inception_date: date
    termination_date: date | None
    calculation_method: Literal["ASSET_WEIGHTED"]
    eligibility_policy_version: str
    source_authority: CompositeSourceAuthority
    created_at: datetime
    created_by: str
    correlation_id: str

    def performance_definition(self) -> CompositeDefinition:
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


class ManageMembershipDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str
    effective_from: date
    effective_to: date | None
    status: Literal["INCLUDED", "EXCLUDED", "PENDING_REVIEW"]
    reason_code: str | None
    discretionary: bool
    source_snapshot_id: str
    approval_ref: str | None = None

    def performance_membership(self, composite_id: str) -> CompositeMembership:
        payload = self.model_dump(exclude={"approval_ref", "reason_code"})
        return CompositeMembership.model_validate(
            {
                **payload,
                "composite_id": composite_id,
                "status_reason": self.reason_code,
            }
        )


class ManageMembershipRevision(_ManageIdentity):
    product_name: Literal["CompositeMembership"]
    membership_revision: str
    policy_version: str
    source_cut_id: str
    decisions: list[ManageMembershipDecision] = Field(min_length=1, max_length=1000)
    decided_at: datetime
    decided_by: str
    correlation_id: str
    supersedes_membership_revision: str | None
    affected_from: date | None
    affected_to: date | None


class ManageUniverseSourceProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_service: str
    product_name: str
    contract_version: str
    authority_scope: Literal["AUTHORITATIVE_UNIVERSE", "POLICY_INPUT", "REFERENCE_INPUT"]
    source_cut_id: str
    source_watermark: str
    content_hash: str


class ManageUniverseAttestation(_ManageIdentity):
    product_name: Literal["CompositeUniverseAttestation"]
    membership_revision: str
    membership_content_hash: str
    attestation_version: str
    coverage_from: date
    coverage_to: date
    policy_version: str
    source_cut_id: str
    source_products: list[ManageUniverseSourceProduct] = Field(min_length=1)
    posture: Literal["COMPLETE", "INCOMPLETE", "UNAVAILABLE"]
    expected_portfolio_ids: list[str] = Field(max_length=1000)
    expected_portfolio_count: int = Field(ge=0, strict=True)
    observed_portfolio_count: int = Field(ge=0, strict=True)
    missing_portfolio_ids: list[str]
    unexpected_portfolio_ids: list[str]
    coverage_gap_portfolio_ids: list[str]
    reason_code: str | None
    attested_at: datetime
    attested_by: str
    correlation_id: str


class CompositeSourceWireEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: dict[str, Any]
    membership: dict[str, Any]
    attestation: dict[str, Any]


class PinnedCompositeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: ManageCompositeDefinition | ManageCompositeDefinitionV2
    membership: ManageMembershipRevision
    attestation: ManageUniverseAttestation
    wire_evidence: CompositeSourceWireEvidence


def admit_pinned_source(
    *,
    command: CompositeMaterializationCommand,
    tenant_id: str,
    definition: dict[str, Any],
    membership: dict[str, Any],
    attestation: dict[str, Any],
) -> PinnedCompositeSource:
    for payload, expected_hash in (
        (definition, command.definition_content_hash),
        (membership, command.membership_content_hash),
        (attestation, command.attestation_content_hash),
    ):
        digest = (
            authority_digest({key: value for key, value in payload.items() if key != "content_hash"})
            if payload.get("product_name") == "CompositeDefinition" and payload.get("product_version") == "v2"
            else source_digest(payload)
        )
        if payload.get("content_hash") != expected_hash or digest != expected_hash:
            raise source_refusal("COMPOSITE_SOURCE_HASH_MISMATCH")
    source = PinnedCompositeSource.model_validate(
        {
            "definition": definition,
            "membership": membership,
            "attestation": attestation,
            "wire_evidence": {"definition": definition, "membership": membership, "attestation": attestation},
        }
    )
    require_pinned_source_scope(source, command=command, tenant_id=tenant_id)
    return source


def require_pinned_source_scope(
    source: PinnedCompositeSource, *, command: CompositeMaterializationCommand, tenant_id: str
) -> None:
    _require_retained_wire_evidence(source)
    if (
        source.definition.content_hash,
        source.membership.content_hash,
        source.attestation.content_hash,
    ) != (command.definition_content_hash, command.membership_content_hash, command.attestation_content_hash):
        raise source_refusal("COMPOSITE_SOURCE_HASH_MISMATCH")
    _admit_identity(source, command=command, tenant_id=tenant_id)
    _admit_definition(source.definition, command=command)
    _admit_universe(source, command=command)
    if isinstance(source.definition, ManageCompositeDefinitionV2):
        admit_authority_profile(
            source.definition,
            command=command,
            tenant_id=tenant_id,
            expected_members=source.attestation.expected_portfolio_ids,
            universe_digest=next(
                item.content_hash
                for item in source.attestation.source_products
                if item.authority_scope == "AUTHORITATIVE_UNIVERSE"
            ),
        )
    _admit_membership_coverage(source, command=command)


def _require_retained_wire_evidence(source: PinnedCompositeSource) -> None:
    # Raw producer wires preserve lexical timestamp/hash inputs. Hashing the
    # normalized DTO would change legitimate Z timestamps to +00:00 on restore.
    for raw, typed in (
        (source.wire_evidence.definition, source.definition),
        (source.wire_evidence.membership, source.membership),
        (source.wire_evidence.attestation, source.attestation),
    ):
        digest = (
            authority_digest({key: value for key, value in raw.items() if key != "content_hash"})
            if isinstance(typed, ManageCompositeDefinitionV2)
            else source_digest(raw)
        )
        if digest != typed.content_hash or type(typed).model_validate(raw) != typed:
            raise source_refusal("COMPOSITE_SOURCE_RETAINED_WIRE_MISMATCH")


def _admit_identity(source: PinnedCompositeSource, *, command: CompositeMaterializationCommand, tenant_id: str) -> None:
    expected = (tenant_id, command.composite_id, command.definition_version)
    if any(
        (item.tenant_id, item.composite_id, item.definition_version) != expected
        for item in (source.definition, source.membership, source.attestation)
    ):
        raise source_refusal("COMPOSITE_SOURCE_SCOPE_MISMATCH")
    membership, attestation = source.membership, source.attestation
    if (membership.membership_revision, membership.source_cut_id, membership.policy_version) != (
        command.membership_revision,
        command.source_cut_id,
        command.policy_version,
    ) or (
        attestation.membership_revision,
        attestation.source_cut_id,
        attestation.policy_version,
        attestation.attestation_version,
        attestation.membership_content_hash,
    ) != (
        command.membership_revision,
        command.source_cut_id,
        command.policy_version,
        command.attestation_version,
        command.membership_content_hash,
    ):
        raise source_refusal("COMPOSITE_SOURCE_REVISION_MISMATCH")


def _admit_definition(
    definition: ManageCompositeDefinition | ManageCompositeDefinitionV2, *, command: CompositeMaterializationCommand
) -> None:
    if isinstance(definition, ManageCompositeDefinitionV2):
        _admit_v2_definition_scope(definition, command)
        return
    ownership = definition.source_authority
    if (
        ownership.definition_owner,
        ownership.membership_owner,
        ownership.member_return_owner,
        ownership.asset_owner,
    ) != (
        "lotus-manage",
        "lotus-manage",
        "lotus-performance",
        "lotus-core",
    ):
        raise source_refusal("COMPOSITE_SOURCE_OWNER_MISMATCH")
    if (
        definition.reporting_currency != command.reporting_currency
        or definition.eligibility_policy_version != command.policy_version
    ):
        raise source_refusal("COMPOSITE_SOURCE_POLICY_MISMATCH")
    if definition.inception_date > command.period_start or (
        definition.termination_date is not None and definition.termination_date < command.period_end
    ):
        raise source_refusal("COMPOSITE_SOURCE_DEFINITION_WINDOW_MISMATCH")


def _admit_v2_definition_scope(
    definition: ManageCompositeDefinitionV2, command: CompositeMaterializationCommand
) -> None:
    if (definition.reporting_currency, definition.eligibility_policy_version) != (
        command.reporting_currency,
        command.policy_version,
    ):
        raise source_refusal("COMPOSITE_SOURCE_POLICY_MISMATCH")
    if date.fromisoformat(definition.inception_date) > command.period_start or (
        definition.termination_date is not None and date.fromisoformat(definition.termination_date) < command.period_end
    ):
        raise source_refusal("COMPOSITE_SOURCE_DEFINITION_WINDOW_MISMATCH")


def _admit_universe(source: PinnedCompositeSource, *, command: CompositeMaterializationCommand) -> None:
    attestation = source.attestation
    _admit_universe_verdict(attestation)
    _admit_universe_coverage(attestation, command=command)
    _admit_universe_authority(attestation, command=command)


def _admit_universe_verdict(attestation: ManageUniverseAttestation) -> None:
    if attestation.posture != "COMPLETE":
        raise source_refusal("COMPOSITE_UNIVERSE_NOT_COMPLETE")
    ids = attestation.expected_portfolio_ids
    if not ids or len(ids) != len(set(ids)) or len(ids) != attestation.expected_portfolio_count:
        raise source_refusal("COMPOSITE_UNIVERSE_COUNT_MISMATCH")
    if any(
        (
            attestation.missing_portfolio_ids,
            attestation.unexpected_portfolio_ids,
            attestation.coverage_gap_portfolio_ids,
            attestation.reason_code,
        )
    ):
        raise source_refusal("COMPOSITE_UNIVERSE_CONTRADICTED")


def _admit_universe_coverage(
    attestation: ManageUniverseAttestation, *, command: CompositeMaterializationCommand
) -> None:
    if (
        attestation.coverage_from > command.period_start
        or attestation.coverage_to < command.period_end
        or attestation.attested_at.tzinfo is None
    ):
        raise source_refusal("COMPOSITE_UNIVERSE_COVERAGE_MISMATCH")


def _admit_universe_authority(
    attestation: ManageUniverseAttestation, *, command: CompositeMaterializationCommand
) -> None:
    authority = [item for item in attestation.source_products if item.authority_scope == "AUTHORITATIVE_UNIVERSE"]
    if len(authority) != 1 or authority[0].source_cut_id != command.source_cut_id:
        raise source_refusal("COMPOSITE_UNIVERSE_AUTHORITY_MISMATCH")
    if any(not item.content_hash or not item.source_watermark for item in attestation.source_products):
        raise source_refusal("COMPOSITE_UNIVERSE_SOURCE_EVIDENCE_MISSING")


def _admit_membership_coverage(source: PinnedCompositeSource, *, command: CompositeMaterializationCommand) -> None:
    decisions = source.membership.decisions
    if set(source.attestation.expected_portfolio_ids) != {item.portfolio_id for item in decisions}:
        raise source_refusal("COMPOSITE_MEMBERSHIP_UNIVERSE_MISMATCH")
    for portfolio_id in source.attestation.expected_portfolio_ids:
        windows = sorted(
            (item for item in decisions if item.portfolio_id == portfolio_id), key=lambda item: item.effective_from
        )
        _admit_nonoverlapping_windows(windows)
        membership_decision_for_window(source, command=command, portfolio_id=portfolio_id).performance_membership(
            command.composite_id
        )
    supplied = {item.portfolio_id for item in command.member_calculations}
    if not supplied <= set(source.attestation.expected_portfolio_ids):
        raise source_refusal("COMPOSITE_MEMBER_REFERENCE_UNEXPECTED")


def _admit_nonoverlapping_windows(windows: list[ManageMembershipDecision]) -> None:
    for previous, current in zip(windows, windows[1:]):
        if previous.effective_to is None or previous.effective_to >= current.effective_from:
            raise source_refusal("COMPOSITE_MEMBERSHIP_OVERLAP")


def _overlaps_window(decision: ManageMembershipDecision, command: CompositeMaterializationCommand) -> bool:
    return decision.effective_from <= command.period_end and (
        decision.effective_to is None or decision.effective_to >= command.period_start
    )


def membership_decision_for_window(
    source: PinnedCompositeSource,
    *,
    command: CompositeMaterializationCommand,
    portfolio_id: str,
) -> ManageMembershipDecision:
    relevant = [
        item
        for item in source.membership.decisions
        if item.portfolio_id == portfolio_id and _overlaps_window(item, command)
    ]
    # A fact has one effective decision; changing membership requires split windows.
    if len(relevant) != 1:
        raise source_refusal("COMPOSITE_MEMBERSHIP_WINDOW_MISMATCH")
    decision = relevant[0]
    if decision.effective_from > command.period_start or (
        decision.effective_to is not None and decision.effective_to < command.period_end
    ):
        raise source_refusal("COMPOSITE_MEMBERSHIP_WINDOW_MISMATCH")
    return decision
