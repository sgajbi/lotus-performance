# app/models/contribution_responses.py
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from core.envelope import Audit, Diagnostics, Meta


class PositionContribution(BaseModel):
    """Details the contribution of a single position."""

    position_id: str
    total_contribution: float
    average_weight: float
    total_return: float
    local_contribution: Optional[float] = None  # ADDED
    fx_contribution: Optional[float] = None  # ADDED


class DailyContribution(BaseModel):
    """Represents the total contribution for a single day."""

    date: date
    total_contribution: float


class PositionDailyContribution(BaseModel):
    """Represents a single day's contribution for a position."""

    date: date
    contribution: float


class PositionContributionSeries(BaseModel):
    """Contains the full contribution time series for a single position."""

    position_id: str
    series: List[PositionDailyContribution]


class ContributionSummary(BaseModel):
    """High-level summary for a multi-level contribution calculation."""

    portfolio_contribution: float
    coverage_mv_pct: float
    weighting_scheme: str
    local_contribution: Optional[float] = None  # ADDED
    fx_contribution: Optional[float] = None  # ADDED


class ContributionRow(BaseModel):
    """Represents a single row within a hierarchical level (e.g., a sector or security)."""

    key: Dict[str, Any]
    contribution: float
    weight_avg: Optional[float] = None
    children_count: Optional[int] = None
    is_other: bool = False
    residual_bp: Optional[float] = None
    local_contribution: Optional[float] = None  # ADDED
    fx_contribution: Optional[float] = None  # ADDED


class ContributionLevel(BaseModel):
    """Contains the full set of results for a single level of the hierarchy."""

    level: int
    name: str
    parent: Optional[str] = None
    rows: List[ContributionRow]


class SinglePeriodContributionResult(BaseModel):
    """Contains the full set of contribution results for a single, resolved period."""

    total_portfolio_return: Optional[float] = None
    total_contribution: Optional[float] = None
    position_contributions: Optional[List[PositionContribution]] = None
    timeseries: Optional[List[DailyContribution]] = None
    by_position_timeseries: Optional[List[PositionContributionSeries]] = None
    summary: Optional[ContributionSummary] = None
    levels: Optional[List[ContributionLevel]] = None


class ContributionResponse(BaseModel):
    """Response model for the Contribution engine."""

    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID
    portfolio_id: str

    results_by_period: Dict[str, SinglePeriodContributionResult]

    # Shared footer
    meta: Meta
    diagnostics: Diagnostics
    audit: Audit


class ContributionAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID
    poll_path: str
    result_path: str
