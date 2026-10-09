"""Pinned calculated member dataset; all financial values use decimal-return units."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.composites import CompositeReturnView, CompositeTWRRequest, CompositeTWRSelectionManifest


class CompositeLinkedContributionRequest(CompositeTWRRequest):
    metric_id: Literal["LINKED_MEMBER_CONTRIBUTION"] = Field(description="Pinned multi-period member contribution.")
    materialization_ids: list[UUID] = Field(
        min_length=1,
        max_length=120,
        description="Exact chronological COMPLETE retained materialization vector, never latest or official selection.",
    )
    method: Literal["CARINO:v1"] = Field(
        default="CARINO:v1", description="Versioned logarithmic member linking method."
    )


class LinkedMemberPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str
    period_start: date
    period_end: date
    return_value: Decimal
    beginning_market_value: Decimal
    weight: Decimal
    contribution: Decimal
    linking_factor: Decimal
    linked_contribution: Decimal
    source_snapshot_id: str
    source_fingerprint: str
    calculation_id: str | None
    restatement_version: str
    restatement_sequence: int


class LinkedMemberTotal(BaseModel):
    portfolio_id: str
    linked_contribution: Decimal
    participating_period_count: int


class CompositeLinkedContributionResponse(BaseModel):
    metric_id: Literal["LINKED_MEMBER_CONTRIBUTION"] = "LINKED_MEMBER_CONTRIBUTION"
    calculation_id: UUID
    composite_id: str
    period_start: date
    period_end: date
    return_view: CompositeReturnView
    reporting_currency: str
    method: Literal["CARINO:v1"] = "CARINO:v1"
    status: Literal["CALCULATED_ANALYSIS"] = "CALCULATED_ANALYSIS"
    qualification: Literal["RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"] = (
        "RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"
    )
    units: Literal["DECIMAL_RETURN"] = "DECIMAL_RETURN"
    constituent_decomposition: Literal["AVAILABLE"] = "AVAILABLE"
    cumulative_return: Decimal
    total_linked_contribution: Decimal
    reconciliation_difference: Decimal
    display_rounding_difference: Decimal
    members: list[LinkedMemberTotal]
    periods: list[LinkedMemberPeriod]
    selection_manifest: CompositeTWRSelectionManifest
