"""Independent rational rate/wealth/money distinctions and strict schedule boundaries."""

from copy import deepcopy
from datetime import date
from decimal import ROUND_DOWN, ROUND_UP, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.composite_model_fees import CompositePeriodicModelFeeProfile
from app.models.composite_scheduled_model_fees import CompositeScheduledModelFeeProfile
from app.services.composite_materialization.model_fee_returns import periodic_model_net_return
from app.services.composite_materialization.model_fee_schedule_rates import (
    scheduled_model_fee_context,
    scheduled_period_fee_fraction,
)
from engine.composites import calculate_asset_weighted_composite_twr
from tests.composite_model_fee_helpers import profile_wire
from tests.composite_scheduled_model_fee_helpers import band_rule, scheduled_profile_wire


def period_entry(*, rule=None, base="100000", first="2026-01-01", last="2026-01-31"):
    wire = scheduled_profile_wire()
    wire.update(effective_from=first, effective_to=last)
    period = wire["periods"][0]
    period.update(period_start=first, period_end=last)
    wire["periods"] = [period]
    entry = period["member_rates"][0]
    entry["fee_base_amount"] = base
    if rule is not None:
        entry["schedule_rule"] = rule
    profile = CompositeScheduledModelFeeProfile.model_validate(wire)
    return profile.periods[0], profile.periods[0].member_rates[0]


def rational_decimal(value):
    with localcontext() as context:
        context.prec = 100
        return Decimal(value.numerator) / Decimal(value.denominator)


@pytest.mark.parametrize(
    "rule,expected",
    [
        (None, Fraction(93, 91250)),
        (band_rule("MARGINAL_TIERED", threshold="50000"), Fraction(31, 45625)),
        (band_rule("WHOLE_AUM_BAND"), Fraction(93, 182500)),
    ],
)
def test_independent_nominal_rate_wealth_haircut_and_implied_money_are_not_fixed_cash_accrual(rule, expected):
    period, entry = period_entry(rule=rule)
    fraction = scheduled_period_fee_fraction(entry, period)
    assert abs(fraction - rational_decimal(expected)) < Decimal("1e-75")
    gross = Decimal("0.02")
    model = periodic_model_net_return(gross, fraction)
    expected_model = Fraction(51, 50) * (1 - expected) - 1
    assert abs(model - rational_decimal(expected_model)) < Decimal("1e-75")
    with localcontext() as context:
        context.prec = 100
        implied_money = Decimal("100000") * (1 + gross) * fraction
        fixed_beginning_money = Decimal("100000") * fraction
        assert abs(implied_money - rational_decimal(102000 * expected)) < Decimal("1e-70")
        assert implied_money > fixed_beginning_money
        assert model != gross - fraction


@pytest.mark.parametrize("base,rate", [("99999.99", "0.01"), ("100000", "0.006"), ("100000.01", "0.006")])
def test_whole_aum_band_uses_lower_inclusive_upper_exclusive_threshold(base, rate):
    period, entry = period_entry(rule=band_rule("WHOLE_AUM_BAND"), base=base)
    expected = Fraction(rate) * Fraction(31, 365)
    assert abs(scheduled_period_fee_fraction(entry, period) - rational_decimal(expected)) < Decimal("1e-75")


@pytest.mark.parametrize("base", ["49999.99", "50000", "50000.01", "100000"])
def test_marginal_tiers_weight_only_assets_in_each_tranche(base):
    period, entry = period_entry(rule=band_rule("MARGINAL_TIERED", threshold="50000"), base=base)
    amount = Fraction(base)
    selected_rate = (min(amount, 50000) * Fraction(1, 100) + max(0, amount - 50000) * Fraction(3, 500)) / amount
    expected = selected_rate * Fraction(31, 365)
    assert abs(scheduled_period_fee_fraction(entry, period) - rational_decimal(expected)) < Decimal("1e-75")


@pytest.mark.parametrize("ambient_precision", [9, 28, 80, 150])
@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
def test_derived_ratio_replays_identically_under_different_caller_decimal_contexts(ambient_precision, rounding):
    period, entry = period_entry(rule=band_rule("MARGINAL_TIERED", threshold="50000"), base="100000.01")
    reference = scheduled_period_fee_fraction(entry, period)
    with localcontext() as context:
        context.prec = ambient_precision
        context.rounding = rounding
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        context.Emin, context.Emax = -9, 9
        original_flags = context.flags.copy()
        assert scheduled_period_fee_fraction(entry, period).as_tuple() == reference.as_tuple()
        assert context.prec == ambient_precision and context.rounding == rounding
        assert context.Emin == -9 and context.Emax == 9
        assert context.traps[Inexact] and context.traps[Rounded] and dict(context.flags) == original_flags


@pytest.mark.parametrize("first,last,days", [("2028-02-01", "2028-02-29", 29), ("2028-01-01", "2028-12-31", 366)])
def test_actual_inclusive_leap_days_keep_fixed_365_denominator(first, last, days):
    period, entry = period_entry(first=first, last=last)
    expected = Fraction(3, 250) * Fraction(days, 365)
    assert abs(scheduled_period_fee_fraction(entry, period) - rational_decimal(expected)) < Decimal("1e-75")


def test_explicit_zero_waiver_and_total_gross_loss_preserve_wealth_domain():
    period, entry = period_entry(rule={"algorithm": "FLAT_ANNUAL", "annual_model_wealth_rate": "0"})
    assert scheduled_period_fee_fraction(entry, period) == 0
    assert periodic_model_net_return(Decimal("0.02"), Decimal(0)) == Decimal("0.02")
    period, entry = period_entry()
    assert periodic_model_net_return(Decimal(-1), scheduled_period_fee_fraction(entry, period)) == -1


def test_valid_annual_rate_can_still_exceed_period_fraction_domain_and_refuses():
    period, entry = period_entry(
        first="2028-01-01",
        last="2028-12-31",
        rule={"algorithm": "FLAT_ANNUAL", "annual_model_wealth_rate": "0.999"},
    )
    with pytest.raises(ValueError, match="Derived period"):
        scheduled_period_fee_fraction(entry, period)


@pytest.mark.parametrize(
    "field,value",
    [
        ("day_count", "ANNUAL_DIVIDED_BY_12"),
        ("accrual_frequency", "DAILY_CHANGING_NAV"),
        ("rate_basis", "EFFECTIVE_ANNUAL_FEE"),
        ("fee_base_basis", "AVERAGE_ASSETS"),
        ("monetary_charge_interpretation", "FIXED_BEGINNING_ASSET_CASH_FEE"),
        ("bundled_fee_context", "WRAP"),
        ("transaction_cost_treatment", "DEDUCT_AGAIN"),
    ],
)
def test_unsupported_or_ambiguous_financial_conventions_refuse(field, value):
    wire = scheduled_profile_wire()
    wire[field] = value
    with pytest.raises(ValidationError):
        CompositeScheduledModelFeeProfile.model_validate(wire)


@pytest.mark.parametrize("base", ["0", "-1", "NaN", "Infinity", "1e5", 100000, True])
def test_missing_positive_exact_decimal_source_base_refuses(base):
    with pytest.raises(ValidationError):
        period_entry(base=base)


@pytest.mark.parametrize("fault", ["gap", "overlap", "bounded_last", "early_unbounded", "inverted", "negative", "one"])
def test_incomplete_or_ambiguous_band_schedules_refuse(fault):
    rule = band_rule("MARGINAL_TIERED")
    if fault == "gap":
        rule["bands"][1]["lower_bound"] = "100001"
    elif fault == "overlap":
        rule["bands"][1]["lower_bound"] = "99999"
    elif fault == "bounded_last":
        rule["bands"][1]["upper_bound"] = "200000"
    elif fault == "early_unbounded":
        rule["bands"][0]["upper_bound"] = None
    elif fault == "inverted":
        rule["bands"][0]["upper_bound"] = "0"
    else:
        rule["bands"][1]["annual_model_wealth_rate"] = "-0.001" if fault == "negative" else "1"
    with pytest.raises(ValidationError):
        period_entry(rule=rule)


def test_new_scope_reuses_complete_calendar_and_preserves_original_periodic_profile_values():
    original = profile_wire()
    assert CompositePeriodicModelFeeProfile.model_validate(original).model_dump(mode="json") == original
    wire = scheduled_profile_wire()
    assert CompositeScheduledModelFeeProfile.model_validate(wire).model_dump(mode="json") == wire
    wire["periods"][1]["period_start"] = "2026-02-02"
    with pytest.raises(ValidationError, match="adjacent"):
        CompositeScheduledModelFeeProfile.model_validate(wire)


@pytest.mark.parametrize("fault", ["inverted_period", "unsorted_members", "duplicate_member"])
def test_scheduled_period_requires_ordered_unique_member_population(fault):
    wire = scheduled_profile_wire()
    period = wire["periods"][0]
    extra = deepcopy(period["member_rates"][0])
    extra.update(entry_id="synthetic.extra.member", member_id="ZZZ")
    period["member_rates"].append(extra)
    valid = CompositeScheduledModelFeeProfile.model_validate(wire)
    assert len(valid.periods[0].member_rates) == 2

    if fault == "inverted_period":
        period["period_start"], period["period_end"] = period["period_end"], period["period_start"]
        message = "period is inverted"
    else:
        if fault == "unsorted_members":
            period["member_rates"].reverse()
        else:
            extra["member_id"] = period["member_rates"][0]["member_id"]
        message = "member rates must be sorted and unique"
    with pytest.raises(ValidationError, match=message):
        CompositeScheduledModelFeeProfile.model_validate(wire)


def test_two_month_unequal_schedule_original_assets_and_independent_cumulative_oracle():
    # This is a numerical engine control. Registered authority and HTTP controls
    # have separate tests; do not interpret these fact-like objects as admission.
    wire = scheduled_profile_wire()
    first, second = wire["periods"]
    first["member_rates"] = [
        {
            "entry_id": "jan.a",
            "member_id": "A",
            "fee_base_amount": "100000",
            "schedule_rule": {"algorithm": "FLAT_ANNUAL", "annual_model_wealth_rate": "0.012"},
        },
        {
            "entry_id": "jan.b",
            "member_id": "B",
            "fee_base_amount": "300000",
            "schedule_rule": band_rule("MARGINAL_TIERED", threshold="100000"),
        },
    ]
    second["member_rates"] = [
        {
            "entry_id": "feb.a",
            "member_id": "A",
            "fee_base_amount": "102000",
            "schedule_rule": {"algorithm": "FLAT_ANNUAL", "annual_model_wealth_rate": "0.01"},
        },
        {
            "entry_id": "feb.b",
            "member_id": "B",
            "fee_base_amount": "297000",
            "schedule_rule": {
                "algorithm": "WHOLE_AUM_BAND",
                "bands": [
                    {"lower_bound": "0", "upper_bound": "250000", "annual_model_wealth_rate": "0.008"},
                    {"lower_bound": "250000", "upper_bound": None, "annual_model_wealth_rate": "0.005"},
                ],
            },
        },
    ]
    profile = CompositeScheduledModelFeeProfile.model_validate(wire)
    gross = (("0.02", "-0.01"), ("-0.01", "0.03"))
    annual = ((Fraction(".012"), Fraction(11, 1500)), (Fraction(".01"), Fraction(".005")))
    expected, facts = [], []
    with localcontext(scheduled_model_fee_context()):
        for index, period in enumerate(profile.periods):
            days = (date.fromisoformat(period.period_end) - date.fromisoformat(period.period_start)).days + 1
            expected_period = Fraction(0)
            total = sum(Fraction(row.fee_base_amount) for row in period.member_rates)
            for member, entry in enumerate(period.member_rates):
                base, g = Decimal(entry.fee_base_amount), Decimal(gross[index][member])
                fraction = scheduled_period_fee_fraction(entry, period)
                value = periodic_model_net_return(g, fraction)
                reference = (1 + Fraction(g)) * (1 - annual[index][member] * days / 365) - 1
                assert abs(Fraction(value) - reference) < Fraction("1e-75")
                expected_period += Fraction(base) * reference / total
                facts.append(
                    SimpleNamespace(
                        composite_id="synthetic.two-month",
                        portfolio_id=entry.member_id,
                        period_start=date.fromisoformat(period.period_start),
                        period_end=date.fromisoformat(period.period_end),
                        return_value=value,
                        return_view="NET_MODEL_FEE",
                        beginning_market_value=base,
                        ending_market_value=base * (1 + g),
                        reporting_currency="USD",
                        calculation_id=None,
                        source_snapshot_id=entry.entry_id,
                        source_fingerprint=entry.entry_id,
                        restatement_version="original." + entry.entry_id,
                        restatement_sequence=index + 1,
                        status="READY",
                        reason_codes=[],
                        source_authority_identity=None,
                    )
                )
            expected.append(expected_period)
        result = calculate_asset_weighted_composite_twr(composite_id="synthetic.two-month", member_return_facts=facts)
    oracle = (1 + expected[0]) * (1 + expected[1]) - 1
    assert oracle == Fraction(40504773158849, 2531275000000000)
    assert abs(Fraction(result.cumulative_return) - oracle) <= Fraction("1e-12")
    for actual, reference in zip(result.period_results, expected, strict=True):
        assert abs(Fraction(actual.return_value) - reference) <= Fraction("1e-12")
    assert [period.beginning_market_value for period in result.period_results] == [Decimal("400000"), Decimal("399000")]
    assert [period.ending_market_value for period in result.period_results] == [Decimal("399000"), Decimal("406890")]
