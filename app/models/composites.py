from __future__ import annotations

from datetime import date as dt_date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CompositeCalculationMethod(StrEnum):
    ASSET_WEIGHTED = "ASSET_WEIGHTED"


class CompositeMembershipStatus(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    PENDING_REVIEW = "PENDING_REVIEW"


class CompositeMemberReturnStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class CompositeSourceAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_owner: str = Field(
        description="Lotus source authority for composite definitions.",
        examples=["lotus-manage"],
    )
    membership_owner: str = Field(
        description="Lotus source authority for effective-dated composite membership.",
        examples=["lotus-manage"],
    )
    member_return_owner: str = Field(
        description="Lotus source authority for persisted member return facts.",
        examples=["lotus-performance"],
    )
    asset_owner: str = Field(
        description="Lotus source authority for beginning and ending member assets.",
        examples=["lotus-core"],
    )
    benchmark_owner: str | None = Field(
        default=None,
        description="Lotus source authority for composite benchmark assignment and benchmark returns.",
        examples=["lotus-core"],
    )
    policy_version: str = Field(
        description="Versioned source-authority policy used to produce this composite contract.",
        examples=["composite-source-authority.v1"],
    )


class CompositeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    composite_id: str = Field(
        min_length=1,
        description="Stable composite identifier owned by the composite definition source authority.",
        examples=["PB_GLOBAL_BALANCED_USD"],
    )
    display_name: str = Field(
        min_length=1,
        description="Private-banking display name for the composite.",
        examples=["Private Banking Global Balanced USD Composite"],
    )
    strategy_code: str = Field(
        min_length=1,
        description="Strategy or mandate grouping code represented by the composite.",
        examples=["GLOBAL_BALANCED"],
    )
    reporting_currency: str = Field(
        min_length=3,
        max_length=3,
        description="ISO currency used for composite reporting.",
        examples=["USD"],
    )
    inception_date: dt_date = Field(
        description="Composite inception date.",
        examples=["2024-01-01"],
    )
    termination_date: dt_date | None = Field(
        default=None,
        description="Optional composite termination date.",
        examples=["2026-12-31"],
    )
    calculation_method: CompositeCalculationMethod = Field(
        default=CompositeCalculationMethod.ASSET_WEIGHTED,
        description="Composite calculation method approved for RFC 049.",
        examples=["ASSET_WEIGHTED"],
    )
    source_authority: CompositeSourceAuthority = Field(
        description="Source authority declaration for definition, membership, return, asset, and benchmark inputs."
    )

    @model_validator(mode="after")
    def validate_definition_dates(self) -> "CompositeDefinition":
        if self.termination_date is not None and self.termination_date < self.inception_date:
            raise ValueError("termination_date cannot be before inception_date")
        return self


class CompositeMembership(BaseModel):
    model_config = ConfigDict(extra="forbid")

    composite_id: str = Field(description="Composite identifier.", examples=["PB_GLOBAL_BALANCED_USD"])
    portfolio_id: str = Field(description="Member portfolio identifier.", examples=["PB_SG_GLOBAL_BAL_001"])
    effective_from: dt_date = Field(description="Inclusive membership start date.", examples=["2026-01-01"])
    effective_to: dt_date | None = Field(
        default=None, description="Inclusive membership end date.", examples=["2026-12-31"]
    )
    status: CompositeMembershipStatus = Field(
        default=CompositeMembershipStatus.INCLUDED,
        description="Membership state for the effective date range.",
        examples=["INCLUDED"],
    )
    status_reason: str | None = Field(
        default=None,
        description="Source-owned reason for exclusion or review status.",
        examples=["below_minimum_asset_threshold"],
    )
    discretionary: bool = Field(
        default=True,
        description="Whether the portfolio is discretionary for composite inclusion.",
        examples=[True],
    )
    source_snapshot_id: str = Field(
        description="Source snapshot identifier used for lineage and replay.",
        examples=["lotus-manage-membership-2026-05-12T00:00:00Z"],
    )

    @model_validator(mode="after")
    def validate_membership_dates(self) -> "CompositeMembership":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be before effective_from")
        if self.status != CompositeMembershipStatus.INCLUDED and not self.status_reason:
            raise ValueError("status_reason is required when membership status is not INCLUDED")
        return self


class CompositeMemberReturnFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    composite_id: str = Field(description="Composite identifier.", examples=["PB_GLOBAL_BALANCED_USD"])
    portfolio_id: str = Field(description="Member portfolio identifier.", examples=["PB_SG_GLOBAL_BAL_001"])
    period_start: dt_date = Field(description="Inclusive member-return period start.", examples=["2026-01-01"])
    period_end: dt_date = Field(description="Inclusive member-return period end.", examples=["2026-01-31"])
    return_value: Decimal = Field(
        description="Persisted member return as a decimal ratio. Example: 0.0125 means 1.25%.",
        examples=["0.0125"],
    )
    beginning_market_value: Decimal = Field(
        ge=0,
        description="Beginning market value used as the member weight basis.",
        examples=["1000000.00"],
    )
    ending_market_value: Decimal = Field(
        ge=0,
        description="Ending market value retained for composite asset reporting.",
        examples=["1012500.00"],
    )
    reporting_currency: str = Field(
        min_length=3,
        max_length=3,
        description="ISO reporting currency for this member-return fact.",
        examples=["USD"],
    )
    calculation_id: str = Field(
        description="Source portfolio calculation id used to produce the member return.",
        examples=["7f2b08b0-58e5-49be-b3ef-7a9cfb0321ce"],
    )
    source_snapshot_id: str = Field(
        description="Source snapshot identifier used for lineage and replay.",
        examples=["portfolio-twr-2026-01-31T23:59:59Z"],
    )
    status: CompositeMemberReturnStatus = Field(
        default=CompositeMemberReturnStatus.READY,
        description="Whether the persisted member-return fact is usable for composite calculation.",
        examples=["READY"],
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="Bounded reason codes explaining degraded, blocked, or unsupported member-return facts.",
        examples=[["missing_final_valuation"]],
    )

    @model_validator(mode="after")
    def validate_fact(self) -> "CompositeMemberReturnFact":
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot be before period_start")
        if self.status != CompositeMemberReturnStatus.READY and not self.reason_codes:
            raise ValueError("reason_codes are required when member return status is not READY")
        return self
