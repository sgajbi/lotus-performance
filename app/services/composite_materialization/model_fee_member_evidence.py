"""Preserve and recheck the original gross receipt beneath every model-fee fact."""

from decimal import Decimal, localcontext
from typing import NoReturn

from app.models.composite_materialization import (
    CompositeMemberOutcomeState,
    CompositeMemberSourceEvidence,
    CompositeModelFeeMemberEvidence,
    CompositeNormalizedMemberSourceEvidence,
    CompositeScheduledModelFeeMemberEvidence,
)
from app.models.composite_scheduled_model_fees import CompositeScheduledMemberFee, CompositeScheduledModelFeePeriod
from app.services.composite_materialization.model_fee_returns import periodic_model_net_return
from app.services.composite_materialization.model_fee_schedule_rates import (
    scheduled_model_fee_context,
    scheduled_period_fee_fraction,
)
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIConflictError, APIError


def _refuse() -> NoReturn:
    raise APIConflictError(
        "Retained model-fee member evidence conflicts with its approved gross source.",
        error_code="COMPOSITE_MODEL_FEE_MEMBER_EVIDENCE_REFUSED",
    )


def _gross_receipt(evidence):
    if isinstance(evidence, CompositeNormalizedMemberSourceEvidence):
        native, version = evidence.native_evidence, "composite-member-source.v3"
    elif isinstance(evidence, CompositeMemberSourceEvidence):
        native, version = evidence, "composite-member-source.v1"
    else:
        _refuse()
    if native.calculation_request.portfolio.metric_basis != "GROSS":
        _refuse()
    return native.period_return, generate_value_fingerprint(evidence, version)[0]


def apply_model_fee_to_outcome(command, outcome, admitted):
    if outcome.state != CompositeMemberOutcomeState.READY:
        return outcome
    gross_return, gross_digest = _gross_receipt(outcome.source_evidence)
    if outcome.fact.return_value != gross_return or outcome.fact.source_snapshot_id != gross_digest:
        _refuse()
    entry = next((row for row in admitted.period.member_rates if row.member_id == outcome.portfolio_id), None)
    if entry is None:
        _refuse()
    fraction = _approved_fee_fraction(entry, admitted.period, outcome.fact)
    common = dict(
        gross_evidence=outcome.source_evidence,
        gross_receipt_digest=gross_digest,
        gross_return=gross_return,
        model_fee_binding=command.model_fee_binding,
    )
    evidence = (
        CompositeScheduledModelFeeMemberEvidence(
            **common, fee_entry=entry.model_copy(deep=True), derived_period_fee_fraction=format(fraction, "f")
        )
        if isinstance(entry, CompositeScheduledMemberFee)
        else CompositeModelFeeMemberEvidence(**common, fee_entry=entry.model_copy(deep=True))
    )
    value = _model_return(gross_return, fraction, entry)
    fact = outcome.fact.model_copy(
        update={
            "return_value": value,
            "source_snapshot_id": generate_value_fingerprint(evidence, evidence.contract_version)[0],
        }
    )
    return outcome.model_copy(
        update={
            "fact": fact,
            "source_evidence": evidence,
            "reason_code": "MEMBER_MODEL_FEE_FACT_VERIFIED",
        }
    )


def require_model_fee_member_evidence(
    command, outcome, *, admitted, tenant_id, currency_normalization_wire, admitted_fx_source=None
):
    from app.services.composite_materialization.member_evidence_policy import _require_base_member_source_evidence

    evidence, fact = outcome.source_evidence, outcome.fact
    if (
        admitted is None
        or fact is None
        or not isinstance(evidence, (CompositeModelFeeMemberEvidence, CompositeScheduledModelFeeMemberEvidence))
    ):
        _refuse()
    gross_return, gross_digest = _require_approved_gross_receipt(command, outcome, admitted)
    gross_fact = fact.model_copy(update={"return_value": gross_return, "source_snapshot_id": gross_digest})
    gross_outcome = outcome.model_copy(update={"fact": gross_fact, "source_evidence": evidence.gross_evidence})
    _require_base_member_source_evidence(
        command,
        gross_outcome,
        tenant_id=tenant_id,
        currency_normalization_wire=currency_normalization_wire,
        admitted_fx_source=admitted_fx_source,
    )
    _require_model_fact(fact, evidence, gross_return, admitted.period)


def _require_approved_gross_receipt(command, outcome, admitted):
    evidence = outcome.source_evidence
    expected_entry = next((row for row in admitted.period.member_rates if row.member_id == outcome.portfolio_id), None)
    gross_return, gross_digest = _gross_receipt(evidence.gross_evidence)
    if (evidence.model_fee_binding, evidence.fee_entry, evidence.gross_return, evidence.gross_receipt_digest) != (
        command.model_fee_binding,
        expected_entry,
        gross_return,
        gross_digest,
    ):
        _refuse()
    return gross_return, gross_digest


def _require_model_fact(fact, evidence, gross_return, period):
    try:
        if isinstance(evidence, CompositeScheduledModelFeeMemberEvidence):
            CompositeScheduledModelFeeMemberEvidence.model_validate(evidence.model_dump(mode="json"))
        fraction = _approved_fee_fraction(evidence.fee_entry, period, fact)
        if isinstance(
            evidence, CompositeScheduledModelFeeMemberEvidence
        ) and evidence.derived_period_fee_fraction != format(fraction, "f"):
            _refuse()
        expected_return = _model_return(gross_return, fraction, evidence.fee_entry)
    except ValueError:
        _refuse()
    if (fact.return_value, fact.source_snapshot_id) != (
        expected_return,
        generate_value_fingerprint(evidence, evidence.contract_version)[0],
    ):
        _refuse()


def _approved_fee_fraction(entry, period, fact):
    if isinstance(entry, CompositeScheduledMemberFee):
        if (
            not isinstance(period, CompositeScheduledModelFeePeriod)
            or Decimal(entry.fee_base_amount) != fact.beginning_market_value
        ):
            _refuse()
        return scheduled_period_fee_fraction(entry, period)
    return Decimal(entry.period_fee_fraction)


def _model_return(gross_return, fraction, entry):
    if isinstance(entry, CompositeScheduledMemberFee):
        with localcontext(scheduled_model_fee_context()):
            return periodic_model_net_return(gross_return, fraction)
    return periodic_model_net_return(gross_return, fraction)


def apply_model_fee_or_refuse(command, outcome, admitted):
    from app.adapters.composite_member_result_source import member_outcome

    if admitted is None:
        return outcome
    try:
        return apply_model_fee_to_outcome(command, outcome, admitted)
    except APIError as error:
        return member_outcome(
            outcome.portfolio_id, code=error.error_code or "COMPOSITE_MODEL_FEE_MEMBER_EVIDENCE_REFUSED"
        )
    except (ValueError, TypeError):
        return member_outcome(outcome.portfolio_id, code="COMPOSITE_MODEL_FEE_MEMBER_EVIDENCE_REFUSED")


def admit_bound_model_fee_source(record, *, tenant_id):
    from app.services.composite_materialization.model_fee_source_admission import admit_model_fee_source

    if record.command.model_fee_binding is None:
        return None
    return admit_model_fee_source(
        record.source, record.command, tenant_id=tenant_id, retained_wire=record.source.model_fee_wire
    )
