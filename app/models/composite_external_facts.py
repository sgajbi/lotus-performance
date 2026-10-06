"""Provider observations, distinct from internal Performance calculations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.models.composite_authority import AuthorityWire, BusinessDate, EvidenceBinding, Identifier

DecimalWire = Annotated[str, Field(strict=True, pattern=r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$", max_length=80)]


class ExternalCashFlow(AuthorityWire):
    business_date: BusinessDate
    amount: DecimalWire
    placement: Literal["BEGINNING_OF_DAY", "END_OF_DAY", "PERIOD_END_AFTER_RETURN"]


class ExternalMemberObservation(AuthorityWire):
    member_id: Identifier
    source_member_id: Identifier
    member_return: DecimalWire
    beginning_assets: DecimalWire
    beginning_assets_date: BusinessDate
    ending_assets: DecimalWire | None
    ending_assets_date: BusinessDate | None
    cash_flows: list[ExternalCashFlow] = Field(max_length=1000)

    @model_validator(mode="after")
    def valid_assets(self) -> ExternalMemberObservation:
        date.fromisoformat(self.beginning_assets_date)
        if Decimal(self.beginning_assets) < 0 or (self.ending_assets is not None and Decimal(self.ending_assets) < 0):
            raise ValueError("Provider asset amounts cannot be negative")
        if (self.ending_assets is None) != (self.ending_assets_date is None):
            raise ValueError("Ending assets require their authoritative business date")
        if self.ending_assets_date is not None:
            date.fromisoformat(self.ending_assets_date)
        return self


class CompositeExternalMemberFacts(AuthorityWire):
    product_name: Literal["CompositeExternalMemberFacts"]
    product_version: Literal["v1"]
    tenant_id: Identifier
    provider_id: Identifier
    revision: Identifier
    watermark: Identifier
    source_cut_id: Identifier
    period_start: BusinessDate
    period_end: BusinessDate
    currency: Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}$")]
    return_view: Literal["GROSS", "NET_ACTUAL"]
    return_units: Literal["DECIMAL_FRACTION"]
    asset_units: Literal["CURRENCY_AMOUNT"]
    method_profile_binding: EvidenceBinding
    rows: list[ExternalMemberObservation] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def exact_window(self) -> CompositeExternalMemberFacts:
        if date.fromisoformat(self.period_end) < date.fromisoformat(self.period_start):
            raise ValueError("Provider period is inverted")
        ids = [row.member_id for row in self.rows]
        if ids != sorted(set(ids)):
            raise ValueError("Provider members must be sorted and unique")
        for row in self.rows:
            _require_row_window(row, self.period_start, self.period_end)
        return self


def _require_row_window(row, period_start, period_end):
    if row.beginning_assets_date != period_start or (
        row.ending_assets_date is not None and row.ending_assets_date != period_end
    ):
        raise ValueError("Provider valuations must bind the requested period")
    for flow in row.cash_flows:
        if (
            not date.fromisoformat(period_start)
            <= date.fromisoformat(flow.business_date)
            <= date.fromisoformat(period_end)
        ):
            raise ValueError("Flow evidence must bind the observed period")
        if flow.placement == "PERIOD_END_AFTER_RETURN" and flow.business_date != period_end:
            raise ValueError("Period-end placement requires the actual period end")
