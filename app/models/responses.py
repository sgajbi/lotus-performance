# app/models/responses.py
from datetime import date as dt_date
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.twr_requests import TWRInputMode
from common.enums import Frequency
from core.envelope import Audit, Diagnostics, Meta


class PerformanceSummary(BaseModel):
    """A summary of performance for a given period (day, month, etc.)."""

    begin_mv: float = Field(
        description="Beginning market value for the bucket in reporting currency.", examples=[1000000.0]
    )
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


TWRDailyCalculationEvidenceStatus = Literal["calculated", "not_calculated"]
TWRDailyLinkabilityStatus = Literal["linkable", "not_linkable", "reset_boundary", "not_calculated"]
TWRDailyEpisodeStatus = Literal["open", "reset_boundary", "no_investment", "not_in_period"]
NumericOutput = float


class TWRDailyCalculationEvidence(BaseModel):
    calculation_method: Literal["flow_neutralized_daily_twr"] = Field(
        default="flow_neutralized_daily_twr",
        description="Daily TWR method used for this portfolio day.",
        examples=["flow_neutralized_daily_twr"],
    )
    denominator_basis: Literal["absolute_begin_mv_plus_bod_cf"] = Field(
        default="absolute_begin_mv_plus_bod_cf",
        description="Capital denominator convention used by the daily return calculation.",
        examples=["absolute_begin_mv_plus_bod_cf"],
    )
    flow_timing_convention: Literal["bod_flows_in_denominator_eod_flows_excluded_from_denominator"] = Field(
        default="bod_flows_in_denominator_eod_flows_excluded_from_denominator",
        description=(
            "External flow timing convention: beginning-of-day flows adjust invested capital; "
            "end-of-day flows are neutralized from performance P&L but do not adjust the denominator."
        ),
        examples=["bod_flows_in_denominator_eod_flows_excluded_from_denominator"],
    )
    begin_mv: NumericOutput = Field(
        description="Beginning market value used for the daily return calculation.",
        examples=[1000000.0],
    )
    end_mv: NumericOutput = Field(
        description="Ending market value used for the daily return calculation.", examples=[1012500.0]
    )
    bod_cf: NumericOutput = Field(description="Beginning-of-day external cash flow.", examples=[25000.0])
    eod_cf: NumericOutput = Field(description="End-of-day external cash flow.", examples=[-10000.0])
    external_inflows: NumericOutput = Field(
        description="Positive external cash flows for the day across beginning-of-day and end-of-day flows.",
        examples=[25000.0],
    )
    external_outflows: NumericOutput = Field(
        description="Absolute value of negative external cash flows for the day across beginning-of-day and end-of-day flows.",
        examples=[10000.0],
    )
    management_fees: NumericOutput = Field(
        description="Management fees included in performance P&L for NET calculations.",
        examples=[125.0],
    )
    signed_adjusted_capital: NumericOutput = Field(
        description="Beginning market value plus beginning-of-day flow before applying the absolute denominator policy.",
        examples=[1025000.0],
    )
    adjusted_capital: NumericOutput = Field(
        description="Absolute beginning market value plus beginning-of-day flow denominator used for the daily return.",
        examples=[1025000.0],
    )
    performance_pnl: NumericOutput = Field(
        description="Flow-neutralized performance P&L numerator used for the daily return.",
        examples=[12500.0],
    )
    daily_return: NumericOutput = Field(
        description="Daily return in percentage-point output units. Example: 1.25 means 1.25%, not 125%.",
        examples=[1.25],
    )
    status: TWRDailyCalculationEvidenceStatus = Field(
        description="Whether the row had enough governed capital basis to calculate a daily return.",
        examples=["calculated"],
    )
    linkability_status: TWRDailyLinkabilityStatus = Field(
        default="linkable",
        description=(
            "Whether this daily return can participate in geometric linking without crossing a reset, "
            "non-calculation, or full-loss boundary."
        ),
        examples=["linkable"],
    )
    episode_status: TWRDailyEpisodeStatus = Field(
        default="open",
        description="TWR episode classification for the day: open, reset boundary, no-investment, or outside the effective period.",
        examples=["open"],
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="Bounded reason codes explaining noteworthy calculation conditions for this row.",
        examples=[["FLOW_NEUTRALIZED_DAILY_RETURN"]],
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Bounded warning codes for rows requiring reviewer attention.",
        examples=[["ZERO_ADJUSTED_CAPITAL"]],
    )


class ComparativeBreakdownItem(BaseModel):
    period: str = Field(description="Resolved bucket label for this breakdown row.", examples=["2026-03"])
    period_start: dt_date = Field(description="Inclusive bucket start date.", examples=["2026-03-01"])
    period_end: dt_date = Field(description="Inclusive bucket end date.", examples=["2026-03-31"])
    period_return: ComparativeReturnValue = Field(description="Bucket return in percentage-point output units.")
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
    calculation_evidence: TWRDailyCalculationEvidence | None = Field(
        default=None,
        description=(
            "Implementation-backed daily TWR calculation evidence for portfolio daily breakdown rows. "
            "This curated evidence is returned independently of optional raw daily_data."
        ),
    )


ComparativeBreakdown = Dict[Frequency, List[ComparativeBreakdownItem]]


class ComparativeAnalyticsBlock(BaseModel):
    summary: ComparativeSummary = Field(description="Summary returns for this block in percentage-point output units.")
    breakdowns: ComparativeBreakdown = Field(
        description="Frequency-aligned breakdowns for this block, using the same percentage-point convention as the summary."
    )
    benchmark_id: str | None = Field(
        default=None, description="Resolved benchmark identifier when this block represents benchmark data."
    )
    benchmark_currency: str | None = Field(
        default=None,
        description="Benchmark base currency when this block represents benchmark data.",
        examples=["USD"],
    )
    input_mode: str | None = Field(
        default=None, description="Resolved input mode used to produce this block.", examples=["stateful"]
    )
    return_source: str | None = Field(
        default=None,
        description="Resolved benchmark return source when this block represents benchmark data.",
        examples=["calculated"],
    )


TWRBenchmarkCalendarAlignmentState = Literal["aligned", "partial_overlap", "no_overlap"]
TWRBenchmarkCurrencyState = Literal[
    "single_currency",
    "base_only",
    "fx_decomposed",
    "vendor_series_base_only",
]


class TWRBenchmarkSupportabilityEvidence(BaseModel):
    return_source: str = Field(
        description="Resolved benchmark return source used by the TWR calculation.",
        examples=["calculated"],
    )
    input_mode: str = Field(description="Resolved benchmark input mode.", examples=["stateful"])
    reporting_currency: str | None = Field(
        default=None,
        description="Requested portfolio reporting currency, when supplied.",
        examples=["USD"],
    )
    benchmark_currency: str | None = Field(
        default=None,
        description="Benchmark currency used for benchmark return evidence.",
        examples=["USD"],
    )
    currency_state: TWRBenchmarkCurrencyState = Field(
        description=(
            "Benchmark currency evidence state. fx_decomposed means Lotus received or derived local and FX "
            "benchmark return components; vendor_series_base_only means the benchmark vendor series only "
            "provides the benchmark return stream."
        ),
        examples=["fx_decomposed"],
    )
    calendar_alignment_state: TWRBenchmarkCalendarAlignmentState = Field(
        description="Portfolio and benchmark daily observation date alignment state for active return supportability.",
        examples=["aligned"],
    )
    portfolio_observation_count: int = Field(
        ge=0,
        description="Number of portfolio daily return observations in the resolved TWR calculation window.",
        examples=[252],
    )
    benchmark_observation_count: int = Field(
        ge=0,
        description="Number of benchmark daily return observations in the resolved TWR calculation window.",
        examples=[252],
    )
    overlapping_observation_count: int = Field(
        ge=0,
        description="Number of dates where both portfolio and benchmark observations are available.",
        examples=[252],
    )
    missing_benchmark_date_count: int = Field(
        ge=0,
        description="Number of portfolio observation dates without a corresponding benchmark observation.",
        examples=[0],
    )
    missing_benchmark_dates_sample: list[dt_date] = Field(
        default_factory=list,
        description="Sample of portfolio observation dates missing benchmark observations.",
        examples=[["2026-01-03"]],
    )
    extra_benchmark_date_count: int = Field(
        ge=0,
        description="Number of benchmark observation dates outside the portfolio observation set.",
        examples=[0],
    )
    extra_benchmark_dates_sample: list[dt_date] = Field(
        default_factory=list,
        description="Sample of benchmark observation dates without portfolio observations.",
        examples=[["2026-01-04"]],
    )
    warning_codes: list[str] = Field(
        default_factory=list,
        description=(
            "Bounded benchmark, FX, and calendar supportability warning codes for TWR active-return evidence."
        ),
        examples=[["BENCHMARK_CALENDAR_GAP"]],
    )


class TWRBenchmarkContext(BaseModel):
    benchmark_id: str = Field(
        description="Resolved benchmark identifier used for this TWR response.", examples=["BMK_GLOBAL_60_40"]
    )
    benchmark_currency: str | None = Field(
        default=None,
        description="Benchmark base currency.",
        examples=["USD"],
    )
    input_mode: str = Field(description="Resolved benchmark input mode.", examples=["stateful"])
    return_source: str = Field(description="Resolved benchmark return source.", examples=["calculated"])
    supportability_evidence: TWRBenchmarkSupportabilityEvidence | None = Field(
        default=None,
        description="Implementation-backed benchmark, FX, and calendar supportability evidence for TWR.",
    )


PerformanceSupportabilityState = Literal["ready", "stale", "degraded", "empty", "error", "unsupported"]
PerformanceSupportabilityReason = Literal[
    "calculation_complete",
    "empty_resolved_periods",
    "insufficient_valuation_points",
    "stale_source_observations",
    "benchmark_unavailable",
    "calculation_quality_issue",
    "unsupported_input_mode",
]
PerformanceFreshnessBucket = Literal["current", "same_day", "stale", "unknown"]

from app.models.source_quality import PerformanceSourceQualityEvidence  # noqa: E402
from app.observability_contracts import PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS  # noqa: E402


class PerformanceCalculationSupportability(BaseModel):
    state: PerformanceSupportabilityState = Field(
        description="Bounded supportability state for the completed performance calculation.",
        examples=["ready"],
    )
    reason: PerformanceSupportabilityReason = Field(
        description="Bounded reason explaining the supportability state.",
        examples=["calculation_complete"],
    )
    freshness_bucket: PerformanceFreshnessBucket = Field(
        description="Freshness bucket comparing resolved source observations with the requested report date.",
        examples=["current"],
    )
    input_row_count: int = Field(
        default=0,
        ge=0,
        description="Resolved valuation observation count used by the calculation.",
        examples=[252],
    )
    resolved_period_count: int = Field(
        default=0,
        ge=0,
        description="Number of requested analysis periods that produced a result block.",
        examples=[3],
    )
    benchmark_row_count: int = Field(
        default=0,
        ge=0,
        description="Resolved benchmark observation count used when benchmark analytics were requested.",
        examples=[252],
    )
    source_quality_evidence: PerformanceSourceQualityEvidence | None = Field(
        default=None,
        description="Implementation-backed source-quality evidence preserved from stateful source normalization.",
    )
    metric_labels: tuple[str, ...] = Field(
        default=PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS,
        description=(
            "Bounded Prometheus label keys emitted by "
            "lotus_performance_calculation_supportability_total. Identifiers, trace or correlation values, "
            "and request or response payload fields must not be metric labels."
        ),
        examples=[list(PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS)],
        json_schema_extra={"example": list(PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS)},
    )


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
    calculation_supportability: PerformanceCalculationSupportability

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
