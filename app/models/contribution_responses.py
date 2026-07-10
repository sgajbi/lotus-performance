# app/models/contribution_responses.py
from datetime import date as dt_date
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.async_polling import DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS
from app.models.contribution_analytics_requests import ContributionInputMode
from app.models.responses import PerformanceCalculationSupportability
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
        description="Average row weight in percentage units. Example: 18.0 means 18%.",
        examples=[18.0],
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


class ContributionSmoothingEvidence(BaseModel):
    """Explains raw, smoothed, and residual contribution posture for one resolved period."""

    smoothing_method: str = Field(description="Requested contribution smoothing method.", examples=["CARINO"])
    status: str = Field(
        description=(
            "Resolved smoothing status for the period. Examples: APPLIED, NOT_REQUESTED, "
            "INVALID_DOMAIN_FALLBACK, NO_CONTRIBUTION_ROWS."
        ),
        examples=["APPLIED"],
    )
    reason_codes: List[str] = Field(
        default_factory=list,
        description=(
            "Machine-readable smoothing and residual reason codes. Examples: CARINO_FACTOR_APPLIED, "
            "CARINO_INVALID_DAILY_LOG_DOMAIN, RESIDUAL_ALLOCATED_TO_RECONCILE_PERIOD."
        ),
    )
    linked_return: float = Field(
        description="Portfolio linked return for the period in percentage-point output units.",
        examples=[-1.0],
    )
    raw_contribution: float = Field(
        description="Sum of raw daily contribution before smoothing in percentage-point output units.",
        examples=[0.0],
    )
    smoothed_contribution: float = Field(
        description="Sum of smoothed daily contribution before period residual allocation in percentage-point output units.",
        examples=[-1.0],
    )
    final_contribution: float = Field(
        description="Final period contribution after any residual allocation in percentage-point output units.",
        examples=[-1.0],
    )
    raw_residual: float = Field(
        description="Linked return minus raw contribution in percentage-point output units.",
        examples=[-1.0],
    )
    smoothing_residual: float = Field(
        description="Linked return minus smoothed contribution before residual allocation in percentage-point output units.",
        examples=[0.0],
    )
    post_allocation_residual: float = Field(
        description="Linked return minus final contribution after residual allocation in percentage-point output units.",
        examples=[0.0],
    )
    residual_allocation_applied: bool = Field(
        description="Whether the service allocated period residual back to contribution rows.",
        examples=[False],
    )
    residual_allocation_basis: Optional[str] = Field(
        default=None,
        description="Basis used for residual allocation when applied.",
        examples=["average_weight"],
    )
    carino_factor_min: Optional[float] = Field(
        default=None,
        description="Minimum Carino factor applied during the period when available.",
        examples=[0.9483283066],
    )
    carino_factor_max: Optional[float] = Field(
        default=None,
        description="Maximum Carino factor applied during the period when available.",
        examples=[1.0483283066],
    )
    invalid_domain_days: int = Field(
        default=0,
        description="Count of period days where Carino logarithmic smoothing was not mathematically valid.",
        examples=[0],
    )


class ContributionSourceEconomicsEvidence(BaseModel):
    """Summarizes source-economics coverage for contribution inputs."""

    input_mode: str = Field(description="Resolved contribution input mode.", examples=["stateful"])
    source_owner: str = Field(
        description="Boundary that supplied the source economics used by contribution.",
        examples=["lotus-core"],
    )
    status: str = Field(
        description="Bounded source-economics posture. Examples: SOURCE_BACKED, SOURCE_LIMITED, CALLER_SUPPLIED.",
        examples=["SOURCE_LIMITED"],
    )
    reason_codes: List[str] = Field(
        default_factory=list,
        description="Machine-readable source-economics reason codes for support and downstream degraded-state UI.",
        examples=[["LOTUS_CORE_ANALYTICS_INPUTS_USED", "COMPONENT_PNL_NOT_SOURCE_AUTHORED"]],
    )
    source_contracts: List[str] = Field(
        default_factory=list,
        description="Source contracts used to build contribution inputs.",
        examples=[["PortfolioTimeseriesInput:v1", "PositionTimeseriesInput:v1"]],
    )
    available_economics: List[str] = Field(
        default_factory=list,
        description="Source-backed economics families available to the calculation.",
        examples=[["portfolio_market_values", "position_market_values", "external_flows", "fx_rates"]],
    )
    unsupported_economics: List[str] = Field(
        default_factory=list,
        description="Economics families not source-authored in the current contribution input contract.",
        examples=[["income_pnl", "tax_pnl", "corporate_action_pnl"]],
    )
    degraded_economics: List[str] = Field(
        default_factory=list,
        description="Economics families present only with degraded or incomplete source evidence.",
        examples=[["unsupported_cash_flow_types"]],
    )
    cash_flow_type_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Counts by canonical or raw source cash_flow_type where stateful rows supplied cash flows.",
        examples=[{"external_flow": 2, "internal_trade_flow": 1, "fee": 1}],
    )
    source_snapshot_count: int = Field(
        default=0,
        ge=0,
        description="Count of upstream snapshots recorded for this calculation in the execution registry.",
        examples=[2],
    )
    source_snapshot_endpoints: List[str] = Field(
        default_factory=list,
        description="Upstream endpoints represented in execution snapshot evidence.",
        examples=[["portfolio_timeseries", "position_timeseries"]],
    )
    classification_dimensions: List[str] = Field(
        default_factory=list,
        description="Classification dimensions available on position metadata.",
        examples=[["asset_class", "sector"]],
    )
    lineage_policy: str = Field(
        description="Where source lineage evidence is retained for replay and support.",
        examples=["stateful contribution preserves lotus-core analytics-input snapshot evidence through executions"],
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
    smoothing_evidence: Optional[ContributionSmoothingEvidence] = Field(
        default=None,
        description="Period-level raw, smoothed, linked-return, residual, and Carino factor evidence.",
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
    calculation_supportability: PerformanceCalculationSupportability = Field(
        description=(
            "Bounded supportability state for completed contribution output, including source freshness and "
            "resolved-input counts used by front-office degraded-state handling."
        )
    )
    source_economics_evidence: ContributionSourceEconomicsEvidence = Field(
        description=(
            "Contribution-specific source-economics posture, including source-backed, unsupported, and "
            "degraded economic input families."
        )
    )

    # Shared footer
    meta: Meta = Field(description="Shared metadata envelope for the calculation.")
    diagnostics: Diagnostics = Field(description="Diagnostic details for the calculation.")
    audit: Audit = Field(description="Audit details for the calculation.")


class ContributionAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(description="Stable calculation handle for the asynchronous contribution request.")
    poll_path: str = Field(
        description="Execution status path to poll until the contribution calculation is complete.",
        examples=["/performance/executions/2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"],
    )
    result_path: str = Field(
        description="Contribution result path to retrieve after the asynchronous calculation completes.",
        examples=["/performance/contribution/results/2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"],
    )
    recommended_poll_after_seconds: int = Field(
        default=DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS,
        description="Recommended minimum seconds to wait before polling poll_path or result_path again.",
        examples=[DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS],
    )
