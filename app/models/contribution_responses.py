# app/models/contribution_responses.py
from datetime import date as dt_date
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.contribution_analytics_requests import ContributionInputMode
from core.envelope import Audit, Diagnostics, Meta


class PositionContribution(BaseModel):
    """Details the contribution of a single position."""

    position_id: str = Field(description="Portfolio position identifier.", examples=["SEC_AAPL_001"])
    total_contribution: float = Field(
        description="Total position contribution to portfolio return in percentage-point output units.",
        examples=[1.24],
    )
    average_weight: float = Field(
        description="Average portfolio weight for the position in percentage units. Example: 25.0 means 25%.",
        examples=[25.0],
    )
    total_return: float = Field(description="Position return in percentage-point output units.", examples=[4.96])
    local_contribution: Optional[float] = Field(
        default=None,
        description="Local-market contribution in percentage-point output units.",
        examples=[1.1],
    )
    fx_contribution: Optional[float] = Field(
        default=None,
        description="FX contribution in percentage-point output units.",
        examples=[0.14],
    )


class DailyContribution(BaseModel):
    """Represents the total contribution for a single day."""

    date: dt_date = Field(description="Business date for this daily contribution.", examples=["2026-03-20"])
    total_contribution: float = Field(
        description="Daily contribution in percentage-point output units.",
        examples=[0.18],
    )


class PositionDailyContribution(BaseModel):
    """Represents a single day's contribution for a position."""

    date: dt_date = Field(description="Business date for this position contribution point.", examples=["2026-03-20"])
    contribution: float = Field(
        description="Position contribution for the date in percentage-point output units.",
        examples=[0.06],
    )


class PositionContributionSeries(BaseModel):
    """Contains the full contribution time series for a single position."""

    position_id: str = Field(description="Portfolio position identifier.", examples=["SEC_AAPL_001"])
    series: List[PositionDailyContribution] = Field(
        description="Daily contribution series for the position in percentage-point output units."
    )


class ContributionSummary(BaseModel):
    """High-level summary for a multi-level contribution calculation."""

    portfolio_contribution: float = Field(
        description="Portfolio-level contribution total in percentage-point output units.",
        examples=[3.48],
    )
    coverage_mv_pct: float = Field(
        description="Covered market value as a percentage of total market value. Example: 98.5 means 98.5%.",
        examples=[98.5],
    )
    weighting_scheme: str = Field(
        description="Weighting scheme used for the contribution rollup.", examples=["average_weight"]
    )
    local_contribution: Optional[float] = Field(
        default=None,
        description="Portfolio local contribution total in percentage-point output units.",
        examples=[3.1],
    )
    fx_contribution: Optional[float] = Field(
        default=None,
        description="Portfolio FX contribution total in percentage-point output units.",
        examples=[0.38],
    )


class ContributionRow(BaseModel):
    """Represents a single row within a hierarchical level (e.g., a sector or security)."""

    key: Dict[str, Any] = Field(description="Resolved grouping key for this row.", examples=[{"sector": "technology"}])
    contribution: float = Field(
        description="Row contribution in percentage-point output units.",
        examples=[1.42],
    )
    weight_avg: Optional[float] = Field(
        default=None,
        description="Average row weight as a decimal ratio. Example: 0.18 means 18%.",
        examples=[0.18],
    )
    children_count: Optional[int] = Field(
        default=None, description="Number of child rows rolled into this row.", examples=[5]
    )
    is_other: bool = Field(default=False, description="Whether the row represents an 'other' rollup bucket.")
    residual_bp: Optional[float] = Field(
        default=None,
        description="Residual not allocated to explicit rows, expressed in basis points.",
        examples=[1.5],
    )
    local_contribution: Optional[float] = Field(
        default=None,
        description="Local-market row contribution in percentage-point output units.",
        examples=[1.21],
    )
    fx_contribution: Optional[float] = Field(
        default=None,
        description="FX row contribution in percentage-point output units.",
        examples=[0.21],
    )


class ContributionLevel(BaseModel):
    """Contains the full set of results for a single level of the hierarchy."""

    level: int = Field(description="Hierarchy depth for this contribution level.", examples=[1])
    name: str = Field(description="Display name for the grouping dimension at this level.", examples=["sector"])
    parent: Optional[str] = Field(
        default=None, description="Parent level name when this level is nested.", examples=["region"]
    )
    rows: List[ContributionRow] = Field(description="Contribution rows for the level.")


class AverageWeightMethodologyStatus(BaseModel):
    """Summarizes the per-period rollout state for reset-aware average-weight methodology."""

    status: str = Field(
        description=(
            "Per-period rollout classification for reset-aware average-weight methodology. "
            "Examples: NO_MATERIAL_SHADOW, PROMOTION_READY, PROMOTED, BLOCKED, UNDER_REVIEW."
        ),
        examples=["PROMOTION_READY"],
    )
    max_shadow_delta_bp: int = Field(
        description="Largest single-position shadow delta for the period, expressed in basis points.",
        examples=[1353],
    )
    is_material_shadow: bool = Field(
        description="Whether the period contains material reset-aware denominator pressure.",
        examples=[True],
    )
    is_cutover_candidate: bool = Field(
        description="Whether the period is analytically clean enough for controlled promotion.",
        examples=[True],
    )
    is_promoted: bool = Field(
        description="Whether the controlled rollout actually promoted reset-aware average-weight output for the period.",
        examples=[False],
    )
    blocker_reason_codes: List[str] = Field(
        default_factory=list,
        description=(
            "Named rollout guardrails that blocked promotion for the period. "
            "Examples: weight_residual, flow_balance, reset_alignment, timeseries_reconciliation."
        ),
    )


class SinglePeriodContributionResult(BaseModel):
    """Contains the full set of contribution results for a single, resolved period."""

    total_portfolio_return: Optional[float] = Field(
        default=None,
        description="Total portfolio return for the period in percentage-point output units.",
        examples=[3.48],
    )
    total_contribution: Optional[float] = Field(
        default=None,
        description="Total summed contribution for the period in percentage-point output units.",
        examples=[3.48],
    )
    position_contributions: Optional[List[PositionContribution]] = Field(
        default=None,
        description="Position-level contribution rows in percentage-point output units.",
    )
    timeseries: Optional[List[DailyContribution]] = Field(
        default=None,
        description="Daily contribution ladder in percentage-point output units.",
    )
    by_position_timeseries: Optional[List[PositionContributionSeries]] = Field(
        default=None,
        description="Per-position daily contribution ladders in percentage-point output units.",
    )
    average_weight_methodology_status: Optional[AverageWeightMethodologyStatus] = Field(
        default=None,
        description="Per-period rollout status for reset-aware average-weight methodology.",
    )
    summary: Optional[ContributionSummary] = Field(
        default=None, description="Summary contribution totals for the period."
    )
    levels: Optional[List[ContributionLevel]] = Field(
        default=None, description="Hierarchical contribution breakdown for the period."
    )


class ContributionResponse(BaseModel):
    """Response model for the Contribution engine."""

    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(description="Stable calculation handle for this contribution request.")
    portfolio_id: str = Field(description="Portfolio identifier.", examples=["PORTFOLIO_001"])
    input_mode: ContributionInputMode = Field(
        default=ContributionInputMode.STATELESS, description="Resolved contribution input mode."
    )

    results_by_period: Dict[str, SinglePeriodContributionResult] = Field(
        description="Per-period contribution outputs. Contribution and return figures are emitted in percentage-point output units unless explicitly labeled otherwise."
    )

    # Shared footer
    meta: Meta = Field(description="Shared metadata envelope for the calculation.")
    diagnostics: Diagnostics = Field(description="Diagnostic details for the calculation.")
    audit: Audit = Field(description="Audit details for the calculation.")


class ContributionAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID
    poll_path: str
    result_path: str
