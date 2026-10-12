"""Installed native source projection replay and exact per-side error evidence."""

import decimal
from fractions import Fraction

from app.adapters.composite_arithmetic_capture.bundle import installed_source_digest, runtime_identity
from app.models.composite_arithmetic_capture import PROFILE, DecimalContextCapture
from app.models.composites import CompositeMemberReturnFact, CompositeTWRRequest, CompositeTWRWindowEvidence
from app.services.calculation_engine_version import calculation_engine_version
from app.services.composite_arithmetic_capture.collector import ArithmeticCollector, refuse
from app.services.composite_arithmetic_capture.response import composite_response
from engine.composites import calculate_asset_weighted_composite_twr


def bounded_fraction(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > 13600:
        refuse("RESOURCE_LIMIT", "Exact precision evidence exceeds its rational envelope.")
    return value


def exact(value):
    value = bounded_fraction(value)
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def mathematical_return(facts):
    # Audit the rational ideal; the native Decimal engine remains the source return calculator.
    periods = {}
    for fact in facts:
        _require_original_fact(fact)
        periods.setdefault((fact.period_start, fact.period_end), []).append(fact)
    growth = Fraction(1)
    for members in periods.values():
        total = bounded_sum(Fraction(item.beginning_market_value) for item in members)
        if total <= 0:
            refuse("SOURCE_COVERAGE_INCOMPLETE", "Positive complete beginning assets are required.")
        weighted = bounded_sum(
            Fraction(item.beginning_market_value) * Fraction(item.return_value) / total for item in members
        )
        growth = bounded_fraction(growth * (1 + weighted))
    return bounded_fraction(growth - 1)


def bounded_sum(values):
    result = Fraction()
    for value in values:
        result = bounded_fraction(result + bounded_fraction(value))
    return result


def _require_original_fact(fact):
    if str(fact.status) != "READY":
        refuse("SOURCE_COVERAGE_INCOMPLETE", "Precision qualification requires complete READY facts.")
    for value in (fact.return_value, fact.beginning_market_value, fact.ending_market_value):
        if value is None or not value.is_finite():
            refuse("SOURCE_COVERAGE_INCOMPLETE", "Finite authoritative source facts are required.")
        if len(str(value)) > 160 or abs(value.as_tuple().exponent) > 160:
            refuse("RESOURCE_LIMIT", "Original fact representation exceeds the supported capture domain.")


def restored_context(payload):
    declared = DecimalContextCapture.model_validate(payload)
    if (
        declared.prec < 28
        or declared.rounding != decimal.ROUND_HALF_EVEN
        or declared.clamp != 0
        or not all(declared.traps[name] for name in ("InvalidOperation", "DivisionByZero", "Overflow"))
    ):
        refuse("UNSUPPORTED_PRECISION_CONTEXT", "The captured arithmetic controls are unsupported.")
    context = decimal.Context(
        prec=declared.prec,
        rounding=declared.rounding,
        Emin=declared.Emin,
        Emax=declared.Emax,
        capitals=declared.capitals,
        clamp=declared.clamp,
    )
    for name, value in declared.traps.items():
        context.traps[getattr(decimal, name)] = value
    for name, value in declared.entry_flags.items():
        context.flags[getattr(decimal, name)] = value
    return context


def _require_adapter(algorithm):
    try:
        installed = installed_source_digest()
    except ValueError:
        refuse("PROJECTION_ADAPTER_UNAVAILABLE", "The installed projection source closure is unavailable.")
    if (
        algorithm["kernel_source_digest"] != installed
        or algorithm["runtime"] != runtime_identity()
        or algorithm["engine_version"] != calculation_engine_version()
        or algorithm["projection_policy"] != "composite-quantize-inherited.v1"
    ):
        refuse("PROJECTION_ADAPTER_UNAVAILABLE", "The captured installed projection adapter is unavailable.")


def qualify(payload, response):
    _require_adapter(payload["algorithm"])
    request = CompositeTWRRequest.model_validate(payload["calculation_request"])
    facts = [CompositeMemberReturnFact.model_validate(item["fact"]) for item in payload["ordered_facts"]]
    windows = [CompositeTWRWindowEvidence.model_validate(item) for item in payload["scope"]["windows"]]
    collector = ArithmeticCollector()
    with decimal.localcontext(restored_context(payload["effective_context"])):
        collector.start(scheduled=payload["context_route"] == "SCHEDULED_COMPONENT_SCOPED")
        result = calculate_asset_weighted_composite_twr(
            composite_id=payload["scope"]["composite_id"], member_return_facts=facts, observer=collector
        )
        collector.finish()
        replayed = composite_response(request, result, windows, payload["source"]["tenant_id"]).model_dump(mode="json")
    if (
        replayed != response
        or collector.checkpoints != payload["checkpoints"]
        or collector.exit_flags != payload["exit_flags"]
    ):
        refuse("SOURCE_PROJECTION_MISMATCH", "Captured source output, checkpoints or status flags differ.")
    ideal = mathematical_return(facts)
    internal = Fraction(payload["checkpoints"][-1]["cumulative_return_before_quantize"])
    reported = Fraction(response["cumulative_return"])
    if abs(reported - internal) > Fraction(1, 2 * 10**12):
        refuse("OUTPUT_QUANTIZATION_MISMATCH", "The captured final output exceeds its HALF_EVEN bound.")
    return {
        "status": "MATCHED",
        "adapter": PROFILE,
        "input_digest": payload["input_digest"],
        "mathematical_return": exact(ideal),
        "internal_return": exact(internal),
        "reported_return": exact(reported),
        "internal_arithmetic_error": exact(internal - ideal),
        "output_quantization_error": exact(reported - internal),
    }
