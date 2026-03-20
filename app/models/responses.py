# app/models/responses.py
from datetime import date
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.twr_requests import TWRInputMode
from common.enums import Frequency
from core.envelope import Audit, Diagnostics, Meta


class PerformanceSummary(BaseModel):
    """A summary of performance for a given period (day, month, etc.)."""

    begin_mv: float
    end_mv: float
    net_cash_flow: float
    period_return_pct: float
    cumulative_return_pct_to_date: Optional[float] = None
    annualized_return_pct: Optional[float] = None


class PerformanceResultItem(BaseModel):
    """Represents a single period's result within a breakdown."""

    period: str
    summary: PerformanceSummary
    daily_data: Optional[List[Dict]] = None


PerformanceBreakdown = Dict[Frequency, List[PerformanceResultItem]]


class ResetEvent(BaseModel):
    date: date
    reason: str
    impacted_rows: int


class PortfolioReturnDecomposition(BaseModel):
    local: float
    fx: float
    base: float


class RelativePerformanceSummary(BaseModel):
    arithmetic_relative_return: float
    cumulative_arithmetic_relative_return: float


class ComparativeReturnValue(BaseModel):
    local: float | None = None
    fx: float | None = None
    base: float


class ComparativeSummary(BaseModel):
    period_return: ComparativeReturnValue
    cumulative_return: ComparativeReturnValue | None = None


class ComparativeBreakdownItem(BaseModel):
    period: str
    period_start: date
    period_end: date
    period_return: ComparativeReturnValue
    cumulative_return: ComparativeReturnValue | None = None
    annualized_return: ComparativeReturnValue | None = None
    daily_data: Optional[List[Dict]] = None


ComparativeBreakdown = Dict[Frequency, List[ComparativeBreakdownItem]]


class ComparativeAnalyticsBlock(BaseModel):
    summary: ComparativeSummary
    breakdowns: ComparativeBreakdown
    benchmark_id: str | None = None
    benchmark_currency: str | None = None
    input_mode: str | None = None
    return_source: str | None = None


class TWRBenchmarkContext(BaseModel):
    benchmark_id: str
    benchmark_currency: str | None = None
    input_mode: str
    return_source: str


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
