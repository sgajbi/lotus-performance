"""Explicit provider facts into the existing materialization pipeline.

No URL/provider supplied by a caller is a resolver configuration. Production
composition remains unavailable until qualified provider and approval adapters exist.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource, member_outcome
from app.models.composite_authority import ManageCompositeDefinitionV2, authority_digest
from app.models.composite_external_facts import CompositeExternalMemberFacts
from app.models.composite_materialization import (
    CompositeMemberMaterializationOutcome,
    CompositeMemberOutcomeState,
    CompositeProviderMemberEvidence,
)
from app.models.composites import CompositeMemberReturnFact
from app.services.composite_materialization.authority_policy import authority_refusal, selection_for_window
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIError


class UnavailableProviderObservations:
    def read(self, *, tenant_id: str, selection) -> dict[str, Any]:
        raise authority_refusal("COMPOSITE_PROVIDER_OBSERVATIONS_UNAVAILABLE")


def provider_observation_source():
    return UnavailableProviderObservations()


def read_observation_wire(command, definition, member_id, fact, *, tenant_id, port):
    selection = selection_for_window(
        definition, member_id=member_id, fact=fact, period_start=command.period_start, period_end=command.period_end
    )
    raw = port.read(tenant_id=tenant_id, selection=selection)
    if authority_digest(raw) != selection.source_digest:
        raise authority_refusal("COMPOSITE_PROVIDER_OBSERVATION_DIGEST_MISMATCH")
    wire = CompositeExternalMemberFacts.model_validate(raw)
    actual = (
        wire.tenant_id,
        wire.provider_id,
        wire.product_name,
        wire.product_version,
        wire.revision,
        wire.watermark,
        wire.source_cut_id,
        wire.period_start,
        wire.period_end,
        wire.currency,
        wire.return_view,
        wire.method_profile_binding,
    )
    expected = (
        tenant_id,
        selection.provider_id,
        selection.source_product,
        selection.source_contract_version,
        selection.source_revision,
        selection.source_watermark,
        selection.source_cut_id,
        str(command.period_start),
        str(command.period_end),
        command.reporting_currency,
        str(command.return_view),
        definition.source_authority.payload.return_method_binding,
    )
    if actual != expected:
        raise authority_refusal("COMPOSITE_PROVIDER_OBSERVATION_SCOPE_MISMATCH")
    row = observation_member_row(wire, definition, member_id)
    return selection, raw, row


def observation_member_row(wire, definition, member_id):
    row = next((row for row in wire.rows if row.member_id == member_id), None)
    identity = next(
        item for item in definition.source_authority.payload.member_identities if item.member_id == member_id
    )
    if row is None or row.source_member_id != identity.source_member_id:
        raise authority_refusal("COMPOSITE_PROVIDER_MEMBER_IDENTITY_MISMATCH")
    return row


class AuthorityCompositeMemberResultSource:
    def __init__(self, definition: ManageCompositeDefinitionV2, *, observations=None, internal_source=None):
        self.definition = definition
        self.observations = observations or provider_observation_source()
        self.internal_source = internal_source or RetainedCompositeMemberResultSource()

    def read_member(
        self,
        command,
        reference,
        *,
        tenant_id,
        membership_snapshot_id,
        request_headers: Mapping[str, str],
        member_id=None,
    ):
        member_id = member_id or reference.portfolio_id
        try:
            return self._resolve(command, reference, member_id, tenant_id, membership_snapshot_id, request_headers)
        except (APIError, ValueError, TypeError, KeyError):
            return member_outcome(member_id, code="COMPOSITE_PROVIDER_OBSERVATION_REFUSED")

    def _resolve(self, command, reference, member_id, tenant_id, membership_snapshot_id, request_headers):
        selections, internal_kinds = member_selections(self.definition, command, member_id)
        internal_outcome = self._read_internal(
            command, reference, member_id, internal_kinds, tenant_id, membership_snapshot_id, request_headers
        )
        if internal_outcome is not None and internal_outcome.state != CompositeMemberOutcomeState.READY:
            return internal_outcome
        if len(internal_kinds) == len(selections) and "ENDING_ASSETS" in selections:
            return internal_outcome
        rows, wires = self._read_external(command, member_id, selections, internal_kinds, tenant_id)
        values = selected_economic_values(selections, internal_kinds, internal_outcome, rows)
        return self._make_outcome(
            command,
            reference,
            member_id,
            membership_snapshot_id,
            selections,
            internal_kinds,
            internal_outcome,
            rows,
            wires,
            values,
        )

    def _read_internal(
        self, command, reference, member_id, internal_kinds, tenant_id, membership_snapshot_id, request_headers
    ):
        from app.services.composite_materialization.internal_authority_policy import require_internal_selection_bindings

        if not internal_kinds:
            return None
        if reference is None:
            return member_outcome(member_id, code="MEMBER_CALCULATION_REFERENCE_REQUIRED")
        outcome = self.internal_source.read_member(
            command,
            reference,
            tenant_id=tenant_id,
            membership_snapshot_id=membership_snapshot_id,
            request_headers=request_headers,
        )
        if outcome.state == CompositeMemberOutcomeState.READY:
            require_internal_selection_bindings(
                self.definition, command, reference, outcome.source_evidence, facts=internal_kinds
            )
        return outcome

    def _read_external(self, command, member_id, selections, internal_kinds, tenant_id):
        rows, wires = {}, {}
        for kind in selections:
            if kind not in internal_kinds:
                _, raw, row = read_observation_wire(
                    command, self.definition, member_id, kind, tenant_id=tenant_id, port=self.observations
                )
                rows[kind] = row
                wires[authority_digest(raw)] = raw
        return rows, wires

    def _make_outcome(
        self,
        command,
        reference,
        member_id,
        membership_snapshot_id,
        selections,
        internal_kinds,
        internal_outcome,
        rows,
        wires,
        values,
    ):
        payload = self.definition.source_authority.payload
        evidence = CompositeProviderMemberEvidence(
            qualification="SYNTHETIC_TEST_ONLY",
            definition_content_hash=self.definition.content_hash,
            profile_digest=self.definition.source_authority.profile_digest,
            membership_snapshot_id=membership_snapshot_id,
            return_selection_id=selections["MEMBER_RETURN"].selection_id,
            asset_selection_id=selections["BEGINNING_ASSETS"].selection_id,
            ending_asset_selection_id=selections["ENDING_ASSETS"].selection_id
            if "ENDING_ASSETS" in selections
            else None,
            observation_wires=list(wires.values()),
            internal_member_evidence=internal_outcome.source_evidence if internal_outcome else None,
        )
        receipt_digest = generate_value_fingerprint(evidence, "composite-member-source.v2")[0]
        identity = selected_source_identity(payload, selections, internal_kinds, rows, member_id)
        fact = CompositeMemberReturnFact(
            composite_id=command.composite_id,
            portfolio_id=member_id,
            period_start=command.period_start,
            period_end=command.period_end,
            return_value=values[0],
            return_view=command.return_view,
            beginning_market_value=values[1],
            ending_market_value=values[2],
            reporting_currency=command.reporting_currency,
            calculation_id=str(reference.calculation_id) if "MEMBER_RETURN" in internal_kinds else None,
            source_authority_identity=identity,
            source_snapshot_id=receipt_digest,
            source_fingerprint=receipt_digest,
            restatement_version=str(command.materialization_id),
            restatement_sequence=command.restatement_sequence,
        )
        return CompositeMemberMaterializationOutcome(
            portfolio_id=member_id,
            state=CompositeMemberOutcomeState.READY,
            reason_code="COMPOSITE_PROVIDER_FACT_VERIFIED_TEST_ONLY",
            retryable=False,
            fact=fact,
            source_evidence=evidence,
        )


def member_selections(definition, command, member_id):
    payload = definition.source_authority.payload
    kinds = ["MEMBER_RETURN", "BEGINNING_ASSETS"]
    if any(selection.fact == "ENDING_ASSETS" for selection in payload.selections):
        kinds.append("ENDING_ASSETS")
    selections = {
        kind: selection_for_window(
            definition, member_id=member_id, fact=kind, period_start=command.period_start, period_end=command.period_end
        )
        for kind in kinds
    }
    providers = {provider.provider_id: provider for provider in payload.providers}
    internal = [
        kind
        for kind, selected in selections.items()
        if providers[selected.provider_id].source_kind != "EXTERNAL_PROVIDER"
    ]
    return selections, internal


def selected_economic_values(selections, internal_kinds, internal_outcome, rows):
    def value(kind, internal_field, external_field):
        if kind in internal_kinds:
            return getattr(internal_outcome.fact, internal_field)
        raw = getattr(rows[kind], external_field)
        return Decimal(raw) if raw is not None else None

    ending = None
    if "ENDING_ASSETS" in selections:
        ending = value("ENDING_ASSETS", "ending_market_value", "ending_assets")
        if ending is None:
            raise authority_refusal("COMPOSITE_ENDING_ASSETS_UNAVAILABLE")
    return (
        value("MEMBER_RETURN", "return_value", "member_return"),
        value("BEGINNING_ASSETS", "beginning_market_value", "beginning_assets"),
        ending,
    )


def selected_source_identity(payload, selections, internal_kinds, rows, member_id):
    external_kind = next((kind for kind in selections if kind not in internal_kinds), None)
    selected = selections[external_kind or "MEMBER_RETURN"]
    source_member_id = selected_member_identity(payload, rows, external_kind, member_id)
    return {
        "source_kind": "INTERNAL" if external_kind is None else "HYBRID" if internal_kinds else "EXTERNAL_PROVIDER",
        "return_source_kind": "LOTUS_PERFORMANCE" if "MEMBER_RETURN" in internal_kinds else "EXTERNAL_PROVIDER",
        "provider_id": selected.provider_id,
        "source_member_id": source_member_id,
        "product_name": selected.source_product,
        "product_version": selected.source_contract_version,
        "source_revision": selected.source_revision,
        "source_digest": selected.source_digest,
    }


def selected_member_identity(payload, rows, external_kind, member_id):
    if external_kind is not None:
        return rows[external_kind].source_member_id
    return next(identity.source_member_id for identity in payload.member_identities if identity.member_id == member_id)
