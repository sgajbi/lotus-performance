"""Build v6 receipts from the original admitted whole financial payload, never category guesses."""

from decimal import Decimal, localcontext

from app.models.composite_authority import EvidenceBinding, authority_digest
from app.models.composite_component_model_fees import CompositeComponentModelFeeProfile
from app.models.composite_materialization import CompositeComponentModelFeeMemberEvidence
from app.services.composite_materialization.component_cost_admission import require_component_costs_before_facts
from app.services.composite_materialization.component_model_fee_returns import component_model_net_return
from app.services.composite_materialization.model_fee_schedule_rates import scheduled_model_fee_context
from engine.numerical_boundary import monetary_arithmetic_context


def component_member_evidence(*, gross_evidence, gross_return, gross_digest, beginning_assets, member_id, admitted):
    require_component_costs_before_facts(admitted)
    if not isinstance(admitted.profile, CompositeComponentModelFeeProfile):
        raise ValueError("Component member evidence requires an admitted component method")
    source = admitted.gross_cost_source.source
    member = next(row for row in source.members if row.evidence.scope.member_id == member_id)
    entry = next(row for row in admitted.period.member_rates if row.member_id == member_id)
    if member.evidence.scope.gross_receipt_digest != gross_digest:
        raise ValueError("Whole cost payload belongs to another original gross receipt")
    _require_reference_wealth(member, beginning_assets, gross_return)
    with localcontext(scheduled_model_fee_context()):
        calculated = component_model_net_return(gross_return, profile=admitted.profile, gross_evidence=member.evidence)
    evidence = CompositeComponentModelFeeMemberEvidence(
        gross_evidence=gross_evidence,
        gross_receipt_digest=gross_digest,
        gross_return=gross_return,
        model_fee_binding=source.model_fee_binding,
        fee_entry=entry,
        gross_component_member=member,
        financial_source_binding=EvidenceBinding(
            product_name=source.product_name,
            product_version=source.product_version,
            revision=source.revision,
            digest=authority_digest(source.model_dump(mode="json")),
        ),
        total_component_fee_fraction=format(calculated.total_component_fee_fraction, "f"),
        already_included_fee_fraction=format(calculated.already_included_fee_fraction, "f"),
        deducted_fee_fraction=format(calculated.deducted_fee_fraction, "f"),
    )
    return evidence, calculated.model_net_return


def _require_reference_wealth(member, beginning_assets, gross_return):
    with localcontext(scheduled_model_fee_context()):
        with monetary_arithmetic_context([beginning_assets, gross_return, Decimal(1)], products=True):
            reference_wealth = beginning_assets * (1 + gross_return)
    if Decimal(member.reference_wealth_amount) != reference_wealth or reference_wealth < 0:
        raise ValueError("Common wealth denominator differs from the original gross source economics")


def prepare_component_outcomes(record, admitted, member_source, *, tenant_id, request_headers, fence):
    """Check the complete selected gross/cost population before the first READY write."""
    from app.services.composite_materialization.member_source_read import read_member_evidence

    if admitted is None or admitted.gross_cost_source is None:
        return None

    references = {row.portfolio_id: row for row in record.command.member_calculations}
    prepared = {}
    for outcome in record.outcomes:
        if outcome.state != "WAITING":
            continue
        reference = references.get(outcome.portfolio_id)
        fence()
        resolved = read_member_evidence(
            record.command,
            reference,
            outcome.portfolio_id,
            member_source,
            tenant_id=tenant_id,
            request_headers=request_headers,
        )
        fence()
        resolved = _preflight_member(record, reference, resolved, admitted)
        if resolved.state != "READY":
            return _refused_population(record, resolved)
        prepared[outcome.portfolio_id] = resolved
    return prepared


def _refused_population(record, refusal):
    from app.adapters.composite_member_result_source import member_outcome

    return {
        row.portfolio_id: member_outcome(row.portfolio_id, code=refusal.reason_code, retryable=refusal.retryable)
        for row in record.outcomes
        if row.state == "WAITING"
    }


def _preflight_member(record, reference, resolved, admitted):
    from app.adapters.composite_member_result_source import member_outcome
    from app.services.composite_materialization.internal_authority_policy import require_internal_selection_bindings
    from app.services.composite_materialization.model_fee_member_evidence import apply_model_fee_or_refuse
    from core.errors import APIError

    if resolved.fact is None:
        return resolved
    try:
        require_internal_selection_bindings(
            record.source.definition,
            record.command,
            reference,
            resolved.source_evidence,
            facts=("MEMBER_RETURN", "BEGINNING_ASSETS", "ENDING_ASSETS"),
        )
        return apply_model_fee_or_refuse(record.command, resolved, admitted)
    except APIError as error:
        return member_outcome(resolved.portfolio_id, code=error.error_code or "COMPOSITE_GROSS_COST_SOURCE_REFUSED")
