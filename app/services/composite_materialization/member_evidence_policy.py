"""Verify retained member evidence without consulting an expired execution record."""

from typing import NoReturn

from app.models.composite_materialization import (
    CompositeMaterializationCommand,
    CompositeMemberMaterializationOutcome,
    CompositeMemberSourceEvidence,
    CompositeModelFeeMemberEvidence,
    CompositeNormalizedMemberSourceEvidence,
)
from app.models.composites import CompositeMemberReturnFact, CompositeReturnView
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIConflictError


def _refuse() -> NoReturn:
    raise APIConflictError(
        "Retained member source evidence conflicts with its immutable fact.",
        error_code="COMPOSITE_MATERIALIZATION_MEMBER_EVIDENCE_REFUSED",
    )


def require_member_source_evidence(
    command: CompositeMaterializationCommand,
    outcome: CompositeMemberMaterializationOutcome,
    *,
    tenant_id: str | None = None,
    currency_normalization_wire: dict | None = None,
    admitted_fx_source=None,
    admitted_model_fee_source=None,
) -> None:
    if command.return_view == CompositeReturnView.NET_MODEL_FEE:
        from app.services.composite_materialization.model_fee_member_evidence import require_model_fee_member_evidence

        require_model_fee_member_evidence(
            command,
            outcome,
            admitted=admitted_model_fee_source,
            tenant_id=tenant_id,
            currency_normalization_wire=currency_normalization_wire,
            admitted_fx_source=admitted_fx_source,
        )
        return
    if isinstance(outcome.source_evidence, CompositeModelFeeMemberEvidence):
        _refuse()
    _require_base_member_source_evidence(
        command,
        outcome,
        tenant_id=tenant_id,
        currency_normalization_wire=currency_normalization_wire,
        admitted_fx_source=admitted_fx_source,
    )


def _require_base_member_source_evidence(
    command, outcome, *, tenant_id=None, currency_normalization_wire=None, admitted_fx_source=None
):
    fact, evidence = outcome.fact, outcome.source_evidence
    _require_normalization_evidence_version(command, evidence)
    if isinstance(evidence, CompositeNormalizedMemberSourceEvidence):
        _require_normalized_member_evidence(
            command,
            outcome,
            tenant_id=tenant_id,
            currency_normalization_wire=currency_normalization_wire,
            admitted_fx_source=admitted_fx_source,
        )
        return
    if fact is None or evidence is None:
        _refuse()
    receipt_digest, _ = generate_value_fingerprint(evidence, "composite-member-source.v1")
    if fact.source_snapshot_id != receipt_digest or evidence.membership_snapshot_id != command.membership_content_hash:
        _refuse()
    input_digest, calculation_digest = generate_value_fingerprint(evidence.calculation_request, evidence.engine_version)
    if (input_digest, calculation_digest) != (evidence.input_fingerprint, evidence.calculation_hash):
        _refuse()
    if (
        generate_value_fingerprint(evidence.source_assets, "portfolio-source-assets.v1")[0]
        != evidence.asset_evidence_fingerprint
    ):
        _refuse()
    _require_member_request_scope(command, outcome.portfolio_id, fact, evidence)
    _require_source_assets_scope(command, fact, evidence)
    _require_core_snapshot_scope(command, outcome.portfolio_id, evidence)


def _require_normalization_evidence_version(command, evidence):
    if command.currency_normalization_binding is not None and not isinstance(
        evidence, CompositeNormalizedMemberSourceEvidence
    ):
        _refuse()


def _require_normalized_member_evidence(
    command, outcome, *, tenant_id, currency_normalization_wire, admitted_fx_source=None
):
    from app.services.composite_materialization.currency_normalization import normalize_member_money
    from app.services.composite_materialization.currency_snapshot_custody import require_fx_snapshot_custody
    from app.services.composite_materialization.currency_source_admission import (
        admit_composite_fx_source,
        fx_resolution_for_command,
    )

    evidence, fact = outcome.source_evidence, outcome.fact
    _require_normalized_identity(command, evidence, fact, tenant_id, currency_normalization_wire)
    native = evidence.native_evidence
    _require_native_receipt(command, native)
    _require_member_request_scope(command, outcome.portfolio_id, fact, native)
    _require_core_snapshot_scope(command, outcome.portfolio_id, native)
    admitted = admitted_fx_source or admit_composite_fx_source(
        fx_resolution_for_command(command, tenant_id=tenant_id), retained_wire=currency_normalization_wire
    )
    member = next(row for row in admitted.source.members if row.member_id == outcome.portfolio_id)
    snapshots = require_fx_snapshot_custody(
        member,
        reporting_currency=command.reporting_currency,
        calculation_id=native.calculation_request.portfolio.calculation_id,
        snapshots=[row.model_dump(mode="json") for row in evidence.fx_snapshots],
    )
    expected = normalize_member_money(command, native, admitted, member_id=outcome.portfolio_id, fx_snapshots=snapshots)
    if (
        expected != evidence
        or generate_value_fingerprint(evidence, "composite-member-source.v3")[0] != fact.source_snapshot_id
    ):
        _refuse()
    if (fact.beginning_market_value, fact.ending_market_value, fact.reporting_currency) != (
        expected.normalized_assets.observations[0].beginning_market_value,
        expected.normalized_assets.observations[-1].ending_market_value,
        expected.normalized_assets.reporting_currency,
    ):
        _refuse()


def _require_normalized_identity(command, evidence, fact, tenant_id, currency_normalization_wire):
    if (
        tenant_id is None
        or fact is None
        or command.currency_normalization_binding is None
        or currency_normalization_wire is None
        or evidence.normalization_binding != command.currency_normalization_binding
    ):
        _refuse()


def _require_native_receipt(command, native):
    if (
        native.membership_snapshot_id != command.membership_content_hash
        or generate_value_fingerprint(native.calculation_request, native.engine_version)
        != (native.input_fingerprint, native.calculation_hash)
        or generate_value_fingerprint(native.source_assets, "portfolio-source-assets.v1")[0]
        != native.asset_evidence_fingerprint
    ):
        _refuse()


def _require_member_request_scope(
    command: CompositeMaterializationCommand,
    portfolio_id: str,
    fact: CompositeMemberReturnFact,
    evidence: CompositeMemberSourceEvidence,
) -> None:
    request = evidence.calculation_request.portfolio
    basis = command.source_metric_basis
    reference = next((item for item in command.member_calculations if item.portfolio_id == portfolio_id), None)
    if reference is None:
        _refuse()
    if (
        str(request.calculation_id),
        request.portfolio_id,
        request.metric_basis,
        request.precision_mode,
        evidence.input_fingerprint,
        evidence.calculation_hash,
        fact.portfolio_id,
        fact.return_value,
    ) != (
        fact.calculation_id,
        portfolio_id,
        basis,
        evidence.precision_mode,
        reference.input_fingerprint,
        reference.calculation_hash,
        portfolio_id,
        evidence.period_return,
    ):
        _refuse()


def _require_source_assets_scope(
    command: CompositeMaterializationCommand,
    fact: CompositeMemberReturnFact,
    evidence: CompositeMemberSourceEvidence,
) -> None:
    assets = evidence.source_assets
    first, last = assets.observations[0], assets.observations[-1]
    if (
        assets.portfolio_currency,
        first.valuation_date,
        last.valuation_date,
        first.beginning_market_value,
        last.ending_market_value,
    ) != (
        command.reporting_currency,
        command.period_start,
        command.period_end,
        fact.beginning_market_value,
        fact.ending_market_value,
    ):
        _refuse()


def _require_core_snapshot_scope(
    command: CompositeMaterializationCommand,
    portfolio_id: str,
    evidence: CompositeMemberSourceEvidence,
) -> None:
    ids = [item.snapshot_id for item in evidence.core_snapshots]
    if len(ids) != len(set(ids)) or any(
        (item.source_identifier, item.request_as_of_date) != (portfolio_id, command.period_end)
        for item in evidence.core_snapshots
    ):
        _refuse()
