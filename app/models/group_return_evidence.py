"""Versioned, source-owned group return evidence for active-risk consumers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GroupReturnEvidenceGrouping(str, Enum):
    """A single canonical group dimension supported by the v1 evidence contract."""

    ASSET_CLASS = "ASSET_CLASS"
    COUNTRY = "COUNTRY"
    CURRENCY = "CURRENCY"
    SECTOR = "SECTOR"


class GroupReturnEvidenceWindow(BaseModel):
    """Inclusive business-date window for group return evidence."""

    start_date: date = Field(examples=["2026-04-01"])
    end_date: date = Field(examples=["2026-04-10"])

    @model_validator(mode="after")
    def validate_range(self) -> "GroupReturnEvidenceWindow":
        if self.start_date > self.end_date:
            raise ValueError("window.start_date cannot be after window.end_date")
        return self


class GroupReturnEvidenceRequest(BaseModel):
    """A tenant-scoped request for one portfolio/benchmark grouping and currency."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "benchmark_id": "BMK_PB_GLOBAL_BALANCED_60_40",
                    "as_of_date": "2026-04-10",
                    "window": {"start_date": "2026-04-01", "end_date": "2026-04-10"},
                    "grouping_dimension": "SECTOR",
                    "reporting_currency": "USD",
                }
            ]
        },
    )

    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="Unique execution identity. It is tenant-bound in the durable execution registry.",
    )
    portfolio_id: str = Field(description="Portfolio whose source valuations define portfolio group returns.")
    benchmark_id: str | None = Field(
        default=None,
        description="Explicit benchmark identifier; when absent the admitted portfolio assignment is resolved from lotus-core.",
    )
    as_of_date: date = Field(description="As-of business date for source selection and benchmark assignment.")
    window: GroupReturnEvidenceWindow = Field(description="Inclusive source-return observation window.")
    grouping_dimension: GroupReturnEvidenceGrouping = Field(
        description="Exactly one canonical group dimension. Multi-dimensional rollups are not inferred by v1."
    )
    reporting_currency: str = Field(
        min_length=3,
        max_length=3,
        description="Required common currency. The request is refused when either source cannot evidence this currency.",
        examples=["USD"],
    )

    @model_validator(mode="after")
    def validate_reporting_currency(self) -> "GroupReturnEvidenceRequest":
        if self.reporting_currency != self.reporting_currency.upper():
            raise ValueError("reporting_currency must be an uppercase ISO 4217 code")
        return self


class GroupReturnEvidenceCoverage(BaseModel):
    """Completeness posture. Incomplete economics are refused rather than silently dropped."""

    status: Literal["COMPLETE"] = "COMPLETE"
    reason_codes: list[str] = Field(default_factory=list)
    observed_dates: list[date] = Field(default_factory=list)
    reconciliation_tolerance: Decimal = Field(
        description="Maximum permitted absolute daily return-ratio difference between source aggregate and group roll-up."
    )


class GroupReturnEvidenceRow(BaseModel):
    """One aligned portfolio/benchmark group observation in decimal-ratio units."""

    date: date
    group_id: str = Field(description="Stable canonical grouping identity, not a presentation label.")
    group_label: str = Field(description="Source classification label for display.")
    portfolio_group_return: Decimal = Field(description="Gross daily TWR for the portfolio group as a decimal ratio.")
    benchmark_group_return: Decimal = Field(description="Daily component-weighted benchmark return for the group.")
    portfolio_weight: Decimal = Field(description="Beginning-capital portfolio group weight.")
    benchmark_weight: Decimal = Field(description="Beginning-of-day benchmark group weight.")
    active_contribution: Decimal = Field(
        description="portfolio_weight * portfolio_group_return - benchmark_weight * benchmark_group_return."
    )


class GroupReturnEvidenceAggregateReturn(BaseModel):
    """Source-aligned daily aggregate returns used to reconcile group active contributions."""

    date: date
    portfolio_return: Decimal
    weighted_portfolio_return: Decimal
    portfolio_reconciliation_delta: Decimal
    benchmark_return: Decimal
    active_return: Decimal
    group_active_contribution_delta: Decimal


class GroupReturnEvidenceSourceSnapshot(BaseModel):
    """Durable source-retrieval evidence; timestamps are intentionally excluded from the economic cut."""

    upstream_endpoint: str
    source_identifier: str
    as_of_date: date = Field(description="Effective source date recorded for the consumed upstream response.")
    request_fingerprint: str
    response_fingerprint: str
    retrieval_status: str


class GroupReturnEvidenceSourceLineage(BaseModel):
    """Execution and source-cut identity for replay and restatement comparison."""

    execution_id: UUID
    tenant_scope: Literal["ADMITTED_TENANT"] = "ADMITTED_TENANT"
    source_cut_id: str = Field(
        description=(
            "Stable SHA-256 digest of the consumed economic context and evidence rows. It excludes execution IDs, "
            "serving timestamps, and unrelated source metadata."
        )
    )
    upstream_revision_status: Literal["NOT_PROVIDED_BY_SOURCE"] = "NOT_PROVIDED_BY_SOURCE"
    snapshots: list[GroupReturnEvidenceSourceSnapshot] = Field(default_factory=list)


class GroupReturnEvidenceResponse(BaseModel):
    """v1 producer response consumed by empirical active-risk attribution; it is not risk attribution itself."""

    contract_version: Literal["v1"] = "v1"
    calculation_id: UUID
    portfolio_id: str
    benchmark_id: str
    as_of_date: date
    window: GroupReturnEvidenceWindow
    grouping_dimension: GroupReturnEvidenceGrouping
    reporting_currency: str
    return_basis: Literal["SOURCE_POSITION_AND_BENCHMARK_COMPONENT_GROSS_TWR"]
    valuation_basis: Literal["SOURCE_REPORTED_BEGINNING_AND_ENDING_MARKET_VALUES"]
    weight_basis: Literal["SIGNED_BEGINNING_CAPITAL_AND_BENCHMARK_BOP_WEIGHT"]
    coverage: GroupReturnEvidenceCoverage
    aggregate_returns: list[GroupReturnEvidenceAggregateReturn]
    rows: list[GroupReturnEvidenceRow]
    source_lineage: GroupReturnEvidenceSourceLineage
