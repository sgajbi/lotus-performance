"""Derive a nominal model wealth fraction; never calculate an actual cash fee."""

from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext

from app.models.composite_scheduled_model_fees import (
    CompositeBandedAnnualModelWealthRate,
    CompositeFlatAnnualModelWealthRate,
    CompositeModelWealthRateBand,
    CompositeScheduledMemberFee,
    CompositeScheduledModelFeePeriod,
)
from engine.numerical_boundary import monetary_arithmetic_context


def scheduled_model_fee_context() -> Context:
    """Fresh named-method policy; never inherit caller rounding, signals or exponents."""
    return Context(
        prec=80,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def scheduled_period_fee_fraction(
    entry: CompositeScheduledMemberFee, period: CompositeScheduledModelFeePeriod
) -> Decimal:
    entry = CompositeScheduledMemberFee.model_validate(entry.model_dump(mode="json"))
    base = Decimal(entry.fee_base_amount)
    days = (date.fromisoformat(period.period_end) - date.fromisoformat(period.period_start)).days + 1
    if days <= 0:
        raise ValueError("Scheduled model wealth rate requires a complete non-inverted period")
    values = [base, Decimal(days), Decimal(365), *_rate_inputs(entry)]
    # Set the ambient floor explicitly before bounded adaptive precision. The
    # same immutable inputs must reproduce identically in callers with any context.
    with localcontext(scheduled_model_fee_context()):
        with monetary_arithmetic_context(values, products=True):
            annual_rate = _annual_model_wealth_rate(base, entry.schedule_rule)
            fraction = annual_rate * Decimal(days) / Decimal(365)
            if not Decimal(0) <= fraction < Decimal(1):
                raise ValueError("Derived period model wealth fraction is outside the supported domain")
            return fraction


def _rate_inputs(entry: CompositeScheduledMemberFee) -> list[Decimal]:
    rule = entry.schedule_rule
    if isinstance(rule, CompositeFlatAnnualModelWealthRate):
        return [Decimal(rule.annual_model_wealth_rate)]
    return [
        Decimal(value)
        for band in rule.bands
        for value in (band.lower_bound, band.upper_bound, band.annual_model_wealth_rate)
        if value is not None
    ]


def _annual_model_wealth_rate(
    base: Decimal, rule: CompositeFlatAnnualModelWealthRate | CompositeBandedAnnualModelWealthRate
) -> Decimal:
    if isinstance(rule, CompositeFlatAnnualModelWealthRate):
        return Decimal(rule.annual_model_wealth_rate)
    if rule.algorithm == "WHOLE_AUM_BAND":
        band = next(band for band in rule.bands if _contains(base, band))
        return Decimal(band.annual_model_wealth_rate)
    weighted_rates = sum(
        (_tranche_assets(base, band) * Decimal(band.annual_model_wealth_rate) for band in rule.bands), Decimal(0)
    )
    return weighted_rates / base


def _contains(base: Decimal, band: CompositeModelWealthRateBand) -> bool:
    return Decimal(band.lower_bound) <= base and (band.upper_bound is None or base < Decimal(band.upper_bound))


def _tranche_assets(base: Decimal, band: CompositeModelWealthRateBand) -> Decimal:
    upper = base if band.upper_bound is None else min(base, Decimal(band.upper_bound))
    return max(Decimal(0), upper - Decimal(band.lower_bound))
