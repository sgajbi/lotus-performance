"""One explicit periodic model-fee convention; decoding never grants approval."""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.models.composite_authority import AuthorityWire, BusinessDate, EvidenceBinding, Identifier
from app.models.composite_currency_normalization import Currency
from app.models.composite_external_facts import DecimalWire

MODEL_FEE_PROFILE_MAX_BYTES = 1024 * 1024


def model_fee_profile_json(wire: dict) -> str:
    canonical = json.dumps(wire, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(canonical.encode("utf-8")) > MODEL_FEE_PROFILE_MAX_BYTES:
        raise ValueError("Model-fee profile exceeds the bounded one-MiB canonical wire")
    return canonical


class CompositePeriodicMemberFee(AuthorityWire):
    entry_id: Identifier = Field(
        description="Immutable approved rate-entry identity, unique across the complete profile."
    )
    member_id: Identifier = Field(
        description="Exact attested composite member identity; never a fabricated Core portfolio."
    )
    period_fee_fraction: DecimalWire = Field(
        description="Explicit post-return period wealth fraction; zero is an approved waiver, never an inferred rate."
    )

    @model_validator(mode="after")
    def supported_rate(self):
        if not Decimal(0) <= Decimal(self.period_fee_fraction) < Decimal(1):
            raise ValueError("Periodic model fee must be finite and within zero inclusive to one exclusive")
        return self


class CompositeModelFeePeriod(AuthorityWire):
    period_start: BusinessDate
    period_end: BusinessDate
    member_rates: list[CompositePeriodicMemberFee] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def ordered_unique_period(self):
        if date.fromisoformat(self.period_end) < date.fromisoformat(self.period_start):
            raise ValueError("Model fee period is inverted")
        members = [entry.member_id for entry in self.member_rates]
        entries = [entry.entry_id for entry in self.member_rates]
        if members != sorted(set(members)) or len(entries) != len(set(entries)):
            raise ValueError("Model fee member rates must be sorted and unique with unique entry identities")
        return self


class CompositeModelFeeProfileBasis(AuthorityWire):
    """Shared immutable scope and cost taxonomy; each method declares its own rates."""

    profile_id: Identifier
    revision: Identifier
    tenant_id: Identifier
    composite_id: Identifier
    method_id: Identifier
    method_revision: Identifier
    schedule_id: Identifier
    schedule_revision: Identifier
    effective_from: BusinessDate
    effective_to: BusinessDate
    calendar_binding: EvidenceBinding
    reporting_currency: Currency
    gross_source_basis: Literal["GROSS"]
    fee_component: Literal["MANAGEMENT_FEE_ONLY"]
    transaction_cost_treatment: Literal["ALREADY_INCLUDED_IN_GROSS"]
    bundled_fee_context: Literal["UNBUNDLED"]
    timing: Literal["END_OF_COMPLETE_PERIOD_AFTER_GROSS_RETURN"]
    transformation: Literal["MULTIPLICATIVE_WEALTH_HAIRCUT"]
    asset_treatment: Literal["UNCHANGED_SOURCE_ASSETS_BEGINNING_ASSET_WEIGHTING"]
    standards_applicability: Literal["NOT_ASSESSED_ENGINEERING_METHOD_ONLY"]


class CompositePeriodicModelFeeProfile(CompositeModelFeeProfileBasis):
    product_name: Literal["CompositePeriodicModelFeeProfile"]
    product_version: Literal["v1"]
    rate_basis: Literal["EXPLICIT_PERIOD_WEALTH_FRACTION"]
    monetary_precision: Literal["DECIMAL_STRICT_NO_INTERMEDIATE_ROUNDING"]
    periods: list[CompositeModelFeePeriod] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def complete_calendar(self):
        require_model_fee_calendar_coverage(
            self.effective_from, self.effective_to, [(row.period_start, row.period_end) for row in self.periods]
        )
        require_unique_model_fee_entries([entry.entry_id for period in self.periods for entry in period.member_rates])
        model_fee_profile_json(self.model_dump(mode="json"))
        return self


def require_model_fee_calendar_coverage(
    effective_from: str, effective_to: str, period_windows: list[tuple[str, str]]
) -> None:
    start, end = date.fromisoformat(effective_from), date.fromisoformat(effective_to)
    if end < start:
        raise ValueError("Model fee profile interval is inverted")
    windows = [(date.fromisoformat(first), date.fromisoformat(last)) for first, last in period_windows]
    if windows[0][0] != start or windows[-1][1] != end:
        raise ValueError("Approved fee calendar must cover the exact profile interval")
    if any(current[0] != previous[1] + timedelta(days=1) for previous, current in zip(windows, windows[1:])):
        raise ValueError("Approved fee periods must be ordered, adjacent and nonoverlapping")


def require_unique_model_fee_entries(entries: list[str]) -> None:
    if len(entries) != len(set(entries)):
        raise ValueError("Model fee rate-entry identities must be unique across the profile")
