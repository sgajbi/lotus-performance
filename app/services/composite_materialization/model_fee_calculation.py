"""Receipt-bound scheduled arithmetic around the canonical composite engine."""

from decimal import localcontext

from app.models.composite_materialization import CompositeMaterializationState
from app.services.composite_materialization.model_fee_schedule_rates import scheduled_model_fee_context
from core.errors import APIUnprocessableEntityError
from engine.composites import calculate_asset_weighted_composite_twr
from engine.numerical_boundary import monetary_arithmetic_context


def is_scheduled_model_fee(method: dict) -> bool:
    return (method.get("product_name"), method.get("product_version")) == ("CompositeScheduledModelFeeProfile", "v1")


def selected_facts_use_scheduled_model_fee(facts, records) -> bool:
    _require_exact_retained_facts(facts, records)
    bindings = [record.command.model_fee_binding for record in records]
    scheduled = _scheduled_bindings(bindings)
    if not scheduled:
        return False
    if any(binding != scheduled[0] for binding in bindings):
        raise APIUnprocessableEntityError(
            "Selected scheduled model-fee facts have incompatible full profile bindings.",
            error_code="COMPOSITE_VECTOR_METHOD_MISMATCH",
        )
    return True


def _scheduled_bindings(bindings):
    return [binding for binding in bindings if binding and is_scheduled_model_fee(binding.model_dump())]


def _require_exact_retained_facts(facts, records):
    retained = [outcome.fact for record in records for outcome in record.outcomes if outcome.fact is not None]

    def by_member(fact):
        return fact.period_start, fact.period_end, fact.portfolio_id, fact.restatement_sequence

    if any(record.state != CompositeMaterializationState.COMPLETE for record in records) or sorted(
        facts, key=by_member
    ) != sorted(retained, key=by_member):
        _refuse_context()


def calculate_with_model_fee_context(*, composite_id, facts, scheduled: bool):
    if not scheduled:
        return calculate_asset_weighted_composite_twr(composite_id=composite_id, member_return_facts=facts)
    values = [
        value
        for fact in facts
        for value in (fact.return_value, fact.beginning_market_value, fact.ending_market_value)
        if value is not None
    ]
    with localcontext(scheduled_model_fee_context()):
        with monetary_arithmetic_context(values, products=True):
            return calculate_asset_weighted_composite_twr(composite_id=composite_id, member_return_facts=facts)


def _refuse_context():
    raise APIUnprocessableEntityError(
        "Selected model-fee facts differ from their complete retained receipts.",
        error_code="COMPOSITE_MODEL_FEE_METHOD_CONTEXT_UNAVAILABLE",
    )
