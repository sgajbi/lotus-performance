from __future__ import annotations

from datetime import date as dt_date
from typing import Literal

from pydantic import BaseModel, Field

SourceQualityState = Literal["clean", "degraded", "stale"]


class PerformanceSourceQualityEvidence(BaseModel):
    source_product: str = Field(
        description="Source data product that supplied the portfolio valuation observations.",
        examples=["PortfolioTimeseriesInput"],
    )
    source_owner: str = Field(
        description="Owning upstream or caller boundary for the source data.", examples=["lotus-core"]
    )
    input_mode: Literal["stateful", "stateless"] = Field(
        description="Execution mode for the portfolio source data.",
        examples=["stateful"],
    )
    quality_state: SourceQualityState = Field(
        description="Bounded source-quality state derived during normalization.",
        examples=["degraded"],
    )
    observation_count: int = Field(ge=0, description="Raw source observation count.", examples=[252])
    valid_valuation_point_count: int = Field(
        ge=0,
        description="Observation count that normalized into canonical valuation points.",
        examples=[251],
    )
    skipped_observation_count: int = Field(
        ge=0,
        description="Observation count skipped because required valuation fields were missing or invalid.",
        examples=[1],
    )
    unsupported_cashflow_count: int = Field(
        ge=0,
        description="Cash-flow rows skipped because their economics role is unsupported for TWR.",
        examples=[2],
    )
    source_conflict_count: int = Field(
        ge=0,
        description="Duplicate or conflicting source observations detected during normalization.",
        examples=[0],
    )
    latest_observation_date: dt_date | None = Field(
        default=None,
        description="Latest normalized source observation date.",
        examples=["2026-03-31"],
    )
    report_end_date: dt_date | None = Field(
        default=None,
        description="Requested report end date used for freshness assessment.",
        examples=["2026-03-31"],
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Bounded source-quality warning codes visible to downstream consumers and support teams.",
        examples=[["UNSUPPORTED_CASHFLOW_LABELS", "MISSING_VALUATION_POINTS"]],
    )
    source_classification_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Counts by normalized source classification when upstream supplied classification metadata.",
        examples=[{"official": 250, "manual_adjustment": 2}],
    )
