"""Explicit synthetic scheduled model wealth methods, never approved customer fees."""

from tests.composite_model_fee_helpers import model_fee_source_inputs, profile_wire


def scheduled_profile_wire():
    return scheduled_from_periodic_wire(profile_wire())


def scheduled_from_periodic_wire(wire):
    wire.update(
        product_name="CompositeScheduledModelFeeProfile",
        profile_id="synthetic.scheduled.model.wealth",
        rate_basis="AUM_SELECTED_NOMINAL_ANNUAL_MODEL_WEALTH_RATE",
        day_count="ACT_365_FIXED_INCLUSIVE",
        accrual_frequency="COMPLETE_RETURN_PERIOD",
        fee_base_basis="VERIFIED_BEGINNING_REPORTING_ASSETS_RATE_SELECTION_ONLY",
        monetary_charge_interpretation="POST_GROSS_WEALTH_FRACTION_NOT_FIXED_CASH_FEE",
        monetary_precision="DECIMAL_MIN_80_DERIVED_RATIO_NO_MONETARY_QUANTIZATION",
    )
    for index, period in enumerate(wire["periods"]):
        rate, base = ("0.012", "0.01")[index], ("100000", "102000")[index]
        entry = period["member_rates"][0]
        del entry["period_fee_fraction"]
        entry.update(fee_base_amount=base, schedule_rule={"algorithm": "FLAT_ANNUAL", "annual_model_wealth_rate": rate})
    return wire


def scheduled_source_inputs():
    _, periodic, _, _ = model_fee_source_inputs()
    wire = scheduled_from_periodic_wire(periodic)
    # These are the exact native synthetic source amounts, not model-adjusted assets.
    bases = {"A": "100", "B": "200", "C": "300"}
    for period in wire["periods"]:
        for entry in period["member_rates"]:
            entry.update(fee_base_amount=bases[entry["member_id"]])
            entry.pop("period_fee_fraction", None)
            entry.setdefault("schedule_rule", {"algorithm": "FLAT_ANNUAL", "annual_model_wealth_rate": "0.012"})
    return model_fee_source_inputs(wire)


def band_rule(algorithm, *, threshold="100000"):
    return {
        "algorithm": algorithm,
        "bands": [
            {"lower_bound": "0", "upper_bound": threshold, "annual_model_wealth_rate": "0.01"},
            {"lower_bound": threshold, "upper_bound": None, "annual_model_wealth_rate": "0.006"},
        ],
    }
