# app/models/responses.py
from datetime import date
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.benchmark_responses import SinglePeriodBenchmarkResult
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


class SinglePeriodPerformanceResult(BaseModel):
    """Contains the full set of TWR results for a single, resolved period."""

    breakdowns: PerformanceBreakdown
    reset_events: Optional[List[ResetEvent]] = None
    portfolio_return: Optional[PortfolioReturnDecomposition] = None


class TWRBenchmarkResponse(BaseModel):
    benchmark_id: str
    benchmark_currency: str
    input_mode: BenchmarkInputMode
    return_source: BenchmarkReturnSource
    results_by_period: Dict[str, SinglePeriodBenchmarkResult]

    model_config = ConfigDict(extra="forbid")


class PerformanceResponse(BaseModel):
    """
    The main response model for a TWR calculation.
    Returns results in canonical multi-period structure under 'results_by_period'.
    """

    calculation_id: UUID
    portfolio_id: str
    input_mode: TWRInputMode = TWRInputMode.STATELESS

    results_by_period: Dict[str, SinglePeriodPerformanceResult]
    benchmark: TWRBenchmarkResponse | None = None

    meta: Meta
    diagnostics: Diagnostics
    audit: Audit

    model_config = ConfigDict(extra="forbid")
