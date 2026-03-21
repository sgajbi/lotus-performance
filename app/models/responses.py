# app/models/responses.py
from datetime import date as dt_date
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.twr_requests import TWRInputMode
from common.enums import Frequency
from core.envelope import Audit, Diagnostics, Meta


class PerformanceSummary(BaseModel):
    """A summary of performance for a given period (day, month, etc.)."""

    begin_mv: float = Field(description="Beginning market value for the bucket in reporting currency.", examples=[1000000.0])
    end_mv: float = Field(description="Ending market value for the bucket in reporting currency.", examples=[1012500.0])
    net_cash_flow: float = Field(
        description="Net external cash flow for the bucket in reporting currency.",
        examples=[25000.0],
    )
    period_return_pct: float = Field(
        description="Bucket return in percentage-point output units. Example: 1.25 means 1.25%, not 125%.",
        examples=[1.25],
    )
    cumulative_return_pct_to_date: Optional[float] = Field(
        default=None,
        description="Cumulative linked return through this bucket in percentage-point output units.",
        examples=[3.42],
    )
    annualized_return_pct: Optional[float] = Field(
        default=None,
        description="Annualized return in percentage-point output units when annualization is applicable.",
        examples=[7.18],
    )


class PerformanceResultItem(BaseModel):
    """Represents a single period's result within a breakdown."""

    period: str = Field(description="Resolved label for this breakdown bucket.", examples=["2026-03"])
    summary: PerformanceSummary = Field(description="Performance summary for the bucket.")
    daily_data: Optional[List[Dict]] = Field(
        default=None,
        description="Optional raw daily detail retained for diagnostic or drill-down use.",
    )


PerformanceBreakdown = Dict[Frequency, List[PerformanceResultItem]]


class ResetEvent(BaseModel):
    date: dt_date = Field(description="Business date on which the reset was applied.", examples=["2026-03-20"])
    reason: str = Field(description="Business or policy reason for the reset.", examples=["cashflow_reset"])
    impacted_rows: int = Field(description="Number of underlying rows impacted by the reset.", examples=[3])


class PortfolioReturnDecomposition(BaseModel):
    local: float = Field(description="Local-market return contribution in percentage points.", examples=[1.12])
    fx: float = Field(description="FX return contribution in percentage points.", examples=[0.18])
    base: float = Field(description="Base-currency total return in percentage points.", examples=[1.3])


class RelativePerformanceSummary(BaseModel):
    arithmetic_relative_return: float = Field(
        description="Arithmetic active return for the resolved period in percentage points.",
        examples=[0.42],
    )
    cumulative_arithmetic_relative_return: float = Field(
        description="Cumulative arithmetic active return through the end of the period in percentage points.",
        examples=[1.08],
    )


class ComparativeReturnValue(BaseModel):
    local: float | None = Field(
        default=None,
        description="Local-market return component in percentage points when the metric decomposes local return.",
        examples=[1.1],
    )
    fx: float | None = Field(
        default=None,
        description="FX return component in percentage points when the metric decomposes FX return.",
        examples=[0.2],
    )
    base: float = Field(description="Total return in percentage-point output units.", examples=[1.3])


class ComparativeSummary(BaseModel):
    period_return: ComparativeReturnValue = Field(
        description="Resolved period return in percentage-point output units."
    )
    cumulative_return: ComparativeReturnValue | None = Field(
        default=None,
        description="Cumulative linked return through the end of the period in percentage-point output units.",
    )


class ComparativeBreakdownItem(BaseModel):
    period: str = Field(description="Resolved bucket label for this breakdown row.", examples=["2026-03"])
    period_start: dt_date = Field(description="Inclusive bucket start date.", examples=["2026-03-01"])
    period_end: dt_date = Field(description="Inclusive bucket end date.", examples=["2026-03-31"])
    period_return: ComparativeReturnValue = Field(
        description="Bucket return in percentage-point output units."
    )
    cumulative_return: ComparativeReturnValue | None = Field(
        default=None,
        description="Cumulative linked return through the end of this bucket in percentage-point output units.",
    )
    annualized_return: ComparativeReturnValue | None = Field(
        default=None,
        description="Annualized return in percentage-point output units when annualization applies.",
    )
    daily_data: Optional[List[Dict]] = Field(
        default=None,
        description="Optional underlying daily detail retained for drill-down use.",
    )


ComparativeBreakdown = Dict[Frequency, List[ComparativeBreakdownItem]]


class ComparativeAnalyticsBlock(BaseModel):
    summary: ComparativeSummary = Field(
        description="Summary returns for this block in percentage-point output units."
    )
    breakdowns: ComparativeBreakdown = Field(
        description="Frequency-aligned breakdowns for this block, using the same percentage-point convention as the summary."
    )
    benchmark_id: str | None = Field(default=None, description="Resolved benchmark identifier when this block represents benchmark data.")
    benchmark_currency: str | None = Field(
        default=None,
        description="Benchmark base currency when this block represents benchmark data.",
        examples=["USD"],
    )
    input_mode: str | None = Field(default=None, description="Resolved input mode used to produce this block.", examples=["stateful"])
    return_source: str | None = Field(
        default=None,
        description="Resolved benchmark return source when this block represents benchmark data.",
        examples=["calculated"],
    )


class TWRBenchmarkContext(BaseModel):
    benchmark_id: str = Field(description="Resolved benchmark identifier used for this TWR response.", examples=["BMK_GLOBAL_60_40"])
    benchmark_currency: str | None = Field(
        default=None,
        description="Benchmark base currency.",
        examples=["USD"],
    )
    input_mode: str = Field(description="Resolved benchmark input mode.", examples=["stateful"])
    return_source: str = Field(description="Resolved benchmark return source.", examples=["calculated"])


class SinglePeriodPerformanceResult(BaseModel):
    """Contains the full set of TWR results for a single, resolved period."""

    portfolio: ComparativeAnalyticsBlock
    benchmark: ComparativeAnalyticsBlock | None = None
    relative_performance: ComparativeAnalyticsBlock | None = None
    reset_events: Optional[List[ResetEvent]] = None


class PerformanceResponse(BaseModel):
    """
    The main response model for a TWR calculation.
    Returns results in canonical multi-period structure under 'results_by_period'.
    """

    calculation_id: UUID
    portfolio_id: str
    input_mode: TWRInputMode = TWRInputMode.STATELESS
    benchmark_context: TWRBenchmarkContext | None = None

    results_by_period: Dict[str, SinglePeriodPerformanceResult]

    meta: Meta
    diagnostics: Diagnostics
    audit: Audit

    model_config = ConfigDict(extra="forbid")


class TWRAcceptedResponse(BaseModel):
    calculation_id: UUID
    poll_path: str
    result_path: str

    model_config = ConfigDict(extra="forbid")
