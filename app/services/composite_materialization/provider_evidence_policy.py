"""Recheck retained provider receipts after writes and repository reload."""

from app.adapters.composite_provider_member_source import AuthorityCompositeMemberResultSource
from app.models.composite_authority import ManageCompositeDefinitionV2, authority_digest
from app.models.composite_materialization import CompositeMemberMaterializationOutcome, CompositeProviderMemberEvidence
from app.models.composites import CompositeMemberReturnFact
from app.services.composite_materialization.member_evidence_policy import require_member_source_evidence
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIConflictError


def _refuse():
    raise APIConflictError(
        "Retained provider evidence conflicts with its pinned fact.",
        error_code="COMPOSITE_PROVIDER_RETAINED_EVIDENCE_REFUSED",
    )


class RetainedProviderObservations:
    def __init__(self, wires):
        self.wires = {authority_digest(wire): wire for wire in wires}
        if len(self.wires) != len(wires):
            _refuse()

    def read(self, *, tenant_id, selection):
        if selection.source_digest not in self.wires:
            _refuse()
        return self.wires[selection.source_digest]


class RetainedInternalMemberSource:
    def __init__(self, command, outcome):
        evidence = outcome.source_evidence.internal_member_evidence
        if evidence is None:
            self.outcome = None
            return
        fact = CompositeMemberReturnFact(
            composite_id=command.composite_id,
            portfolio_id=outcome.portfolio_id,
            period_start=command.period_start,
            period_end=command.period_end,
            return_value=evidence.period_return,
            return_view=command.return_view,
            beginning_market_value=evidence.source_assets.observations[0].beginning_market_value,
            ending_market_value=evidence.source_assets.observations[-1].ending_market_value,
            reporting_currency=command.reporting_currency,
            calculation_id=str(evidence.calculation_request.portfolio.calculation_id),
            source_snapshot_id=generate_value_fingerprint(evidence, "composite-member-source.v1")[0],
            source_fingerprint=evidence.calculation_hash,
            restatement_version=str(command.materialization_id),
            restatement_sequence=command.restatement_sequence,
        )
        self.outcome = CompositeMemberMaterializationOutcome(
            portfolio_id=outcome.portfolio_id,
            state="READY",
            reason_code="MEMBER_FACT_VERIFIED",
            retryable=False,
            fact=fact,
            source_evidence=evidence,
        )
        require_member_source_evidence(command, self.outcome)

    def read_member(self, *args, **kwargs):
        if self.outcome is None:
            _refuse()
        return self.outcome


def require_provider_member_evidence(source, command, outcome) -> None:
    evidence, fact = outcome.source_evidence, outcome.fact
    if (
        not isinstance(source.definition, ManageCompositeDefinitionV2)
        or not isinstance(evidence, CompositeProviderMemberEvidence)
        or fact is None
    ):
        _refuse()
    reference = next((ref for ref in command.member_calculations if ref.portfolio_id == outcome.portfolio_id), None)
    adapter = AuthorityCompositeMemberResultSource(
        source.definition,
        admitted_source=source,
        observations=RetainedProviderObservations(evidence.observation_wires),
        internal_source=RetainedInternalMemberSource(command, outcome),
    )
    expected = adapter.read_member(
        command,
        reference,
        tenant_id=source.definition.tenant_id,
        membership_snapshot_id=command.membership_content_hash,
        request_headers={},
        member_id=outcome.portfolio_id,
    )
    if expected.fact != fact or expected.source_evidence != evidence:
        _refuse()
