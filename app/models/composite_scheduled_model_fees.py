"""Explicit AUM-selected model wealth rates, never fixed monetary fee postings."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.models.composite_authority import AuthorityWire, BusinessDate, Identifier
from app.models.composite_external_facts import DecimalWire
from app.models.composite_model_fees import (
    CompositeModelFeeProfileBasis,
    model_fee_profile_json,
    require_model_fee_calendar_coverage,
    require_unique_model_fee_entries,
)


def _require_annual_model_rate(rate: str) -> None:
    if not Decimal(0) <= Decimal(rate) < Decimal(1):
        raise ValueError("Annual model wealth rate must be within zero inclusive to one exclusive")


class CompositeFlatAnnualModelWealthRate(AuthorityWire):
    algorithm: Literal["FLAT_ANNUAL"]
    annual_model_wealth_rate: DecimalWire

    @model_validator(mode="after")
    def valid_rate(self):
        _require_annual_model_rate(self.annual_model_wealth_rate)
        return self


class CompositeModelWealthRateBand(AuthorityWire):
    lower_bound: DecimalWire
    upper_bound: DecimalWire | None
    annual_model_wealth_rate: DecimalWire

    @model_validator(mode="after")
    def valid_band(self):
        _require_annual_model_rate(self.annual_model_wealth_rate)
        lower = Decimal(self.lower_bound)
        if lower < 0 or (self.upper_bound is not None and Decimal(self.upper_bound) <= lower):
            raise ValueError("Model wealth-rate band must be nonnegative with an increasing upper bound")
        return self


class CompositeBandedAnnualModelWealthRate(AuthorityWire):
    algorithm: Literal["MARGINAL_TIERED", "WHOLE_AUM_BAND"]
    bands: list[CompositeModelWealthRateBand] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def complete_bands(self):
        expected_lower: Decimal | None = Decimal(0)
        for band in self.bands:
            if expected_lower is None or Decimal(band.lower_bound) != expected_lower:
                raise ValueError("Model wealth-rate bands must cover zero upward without gaps or overlap")
            expected_lower = None if band.upper_bound is None else Decimal(band.upper_bound)
        if expected_lower is not None:
            raise ValueError("The final model wealth-rate band must be unbounded")
        return self


CompositeAnnualModelWealthRate = Annotated[
    CompositeFlatAnnualModelWealthRate | CompositeBandedAnnualModelWealthRate,
    Field(discriminator="algorithm"),
]


class CompositeScheduledMemberFee(AuthorityWire):
    entry_id: Identifier
    member_id: Identifier
    fee_base_amount: DecimalWire = Field(
        description="Exact verified beginning reporting-currency assets, used only to select the model wealth rate."
    )
    schedule_rule: CompositeAnnualModelWealthRate

    @model_validator(mode="after")
    def positive_rate_selection_base(self):
        if Decimal(self.fee_base_amount) <= 0:
            raise ValueError("Scheduled model wealth-rate selection requires strictly positive beginning assets")
        return self


class CompositeScheduledModelFeePeriod(AuthorityWire):
    period_start: BusinessDate
    period_end: BusinessDate
    member_rates: list[CompositeScheduledMemberFee] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def ordered_complete_period(self):
        if date.fromisoformat(self.period_end) < date.fromisoformat(self.period_start):
            raise ValueError("Scheduled model fee period is inverted")
        members = [entry.member_id for entry in self.member_rates]
        if members != sorted(set(members)):
            raise ValueError("Scheduled model fee member rates must be sorted and unique")
        require_unique_model_fee_entries([entry.entry_id for entry in self.member_rates])
        return self


class CompositeScheduledModelFeeProfile(CompositeModelFeeProfileBasis):
    product_name: Literal["CompositeScheduledModelFeeProfile"]
    product_version: Literal["v1"]
    rate_basis: Literal["AUM_SELECTED_NOMINAL_ANNUAL_MODEL_WEALTH_RATE"]
    day_count: Literal["ACT_365_FIXED_INCLUSIVE"]
    accrual_frequency: Literal["COMPLETE_RETURN_PERIOD"]
    fee_base_basis: Literal["VERIFIED_BEGINNING_REPORTING_ASSETS_RATE_SELECTION_ONLY"]
    monetary_charge_interpretation: Literal["POST_GROSS_WEALTH_FRACTION_NOT_FIXED_CASH_FEE"]
    monetary_precision: Literal["DECIMAL_MIN_80_DERIVED_RATIO_NO_MONETARY_QUANTIZATION"]
    periods: list[CompositeScheduledModelFeePeriod] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def complete_calendar(self):
        require_model_fee_calendar_coverage(
            self.effective_from, self.effective_to, [(row.period_start, row.period_end) for row in self.periods]
        )
        require_unique_model_fee_entries([entry.entry_id for period in self.periods for entry in period.member_rates])
        model_fee_profile_json(self.model_dump(mode="json"))
        return self
