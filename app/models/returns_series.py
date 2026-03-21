from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime as dt_datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.benchmark_analytics_requests import BenchmarkReturnSource


class ReturnsWindowMode(str, Enum):
    EXPLICIT = "EXPLICIT"
    RELATIVE = "RELATIVE"


class ReturnsRelativePeriod(str, Enum):
    MTD = "MTD"
    QTD = "QTD"
    YTD = "YTD"
    ONE_YEAR = "ONE_YEAR"
    THREE_YEAR = "THREE_YEAR"
    FIVE_YEAR = "FIVE_YEAR"
    SI = "SI"
    YEAR = "YEAR"


class ReturnsFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class MetricBasis(str, Enum):
    NET = "NET"
    GROSS = "GROSS"


class MissingDataPolicy(str, Enum):
    FAIL_FAST = "FAIL_FAST"
    ALLOW_PARTIAL = "ALLOW_PARTIAL"
    STRICT_INTERSECTION = "STRICT_INTERSECTION"


class FillMethod(str, Enum):
    NONE = "NONE"
    FORWARD_FILL = "FORWARD_FILL"
    ZERO_FILL = "ZERO_FILL"


class CalendarPolicy(str, Enum):
    MARKET = "MARKET"
    BUSINESS = "BUSINESS"
    CALENDAR = "CALENDAR"


class InputMode(str, Enum):
    STATELESS = "stateless"
    STATEFUL = "stateful"


class DayCountBasis(str, Enum):
    ACT_365 = "ACT_365"
    ACT_360 = "ACT_360"
    THIRTY_360 = "THIRTY_360"


class ReturnPoint(BaseModel):
    date: dt_date = Field(description="Business date for this return observation.", examples=["2026-02-26"])
    return_value: Decimal = Field(
        description="Simple period return as a decimal ratio. Example: 0.0012 means 0.12% (12 bps), not 1.2%.",
        examples=["0.0012"],
    )


class ReturnsWindow(BaseModel):
    mode: ReturnsWindowMode
    from_date: dt_date | None = None
    to_date: dt_date | None = None
    period: ReturnsRelativePeriod | None = None
    year: int | None = None

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "ReturnsWindow":
        if self.mode == ReturnsWindowMode.EXPLICIT:
            if self.from_date is None or self.to_date is None:
                raise ValueError("from_date and to_date are required when mode=EXPLICIT")
            if self.from_date > self.to_date:
                raise ValueError("from_date cannot be after to_date")
        if self.mode == ReturnsWindowMode.RELATIVE:
            if self.period is None:
                raise ValueError("period is required when mode=RELATIVE")
            if self.period == ReturnsRelativePeriod.YEAR and self.year is None:
                raise ValueError("year is required when period=YEAR")
        return self


class SeriesSelection(BaseModel):
    include_portfolio: bool = True
    include_benchmark: bool = False
    include_risk_free: bool = False


class BenchmarkSpec(BaseModel):
    benchmark_id: str | None = None
    return_source: BenchmarkReturnSource = BenchmarkReturnSource.CALCULATED


class RiskFreeSpec(BaseModel):
    rate_series_ref: str | None = None
    day_count_basis: DayCountBasis | None = None


class DataPolicy(BaseModel):
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.FAIL_FAST
    fill_method: FillMethod = FillMethod.NONE
    calendar_policy: CalendarPolicy = CalendarPolicy.BUSINESS
    max_gap_days: int | None = Field(default=None, ge=1, le=365)


class StatelessInput(BaseModel):
    portfolio_returns: list[ReturnPoint]
    benchmark_returns: list[ReturnPoint] | None = None
    risk_free_returns: list[ReturnPoint] | None = None


class StatefulInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReturnsSeriesRequest(BaseModel):
    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this returns-series calculation request.",
    )
    portfolio_id: str = Field(description="Portfolio identifier.", examples=["DEMO_DPM_EUR_001"])
    as_of_date: dt_date = Field(description="As-of date for window resolution.", examples=["2026-02-27"])
    window: ReturnsWindow
    frequency: ReturnsFrequency = ReturnsFrequency.DAILY
    metric_basis: MetricBasis = MetricBasis.NET
    reporting_currency: str | None = Field(default=None, description="Target reporting currency.", examples=["USD"])
    series_selection: SeriesSelection = Field(default_factory=SeriesSelection)
    benchmark: BenchmarkSpec | None = None
    risk_free: RiskFreeSpec | None = None
    data_policy: DataPolicy = Field(default_factory=DataPolicy)
    input_mode: InputMode = InputMode.STATELESS
    stateless_input: StatelessInput | None = None
    stateful_input: StatefulInput | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> "ReturnsSeriesRequest":
        if self.input_mode == InputMode.STATELESS and self.stateless_input is None:
            raise ValueError("stateless_input is required when input_mode=stateless")
        if self.input_mode == InputMode.STATEFUL and self.stateful_input is None:
            raise ValueError("stateful_input is required when input_mode=stateful")
        if self.input_mode == InputMode.STATELESS and self.stateful_input is not None:
            raise ValueError("stateful_input must be null when input_mode=stateless")
        if self.input_mode == InputMode.STATEFUL and self.stateless_input is not None:
            raise ValueError("stateless_input must be null when input_mode=stateful")
        if self.series_selection.include_benchmark and self.input_mode == InputMode.STATELESS:
            if not self.stateless_input or not self.stateless_input.benchmark_returns:
                raise ValueError("benchmark_returns are required when include_benchmark=true in stateless mode")
        if self.series_selection.include_risk_free and self.input_mode == InputMode.STATELESS:
            if not self.stateless_input or not self.stateless_input.risk_free_returns:
                raise ValueError("risk_free_returns are required when include_risk_free=true in stateless mode")
        if self.input_mode == InputMode.STATELESS and self.benchmark is not None:
            if self.benchmark.benchmark_id is not None:
                raise ValueError("benchmark.benchmark_id is only supported in stateful mode for returns-series")
            if self.benchmark.return_source != BenchmarkReturnSource.CALCULATED:
                raise ValueError("benchmark.return_source is only supported in stateful mode for returns-series")
        return self


class ResolvedWindow(BaseModel):
    start_date: dt_date
    end_date: dt_date
    resolved_period_label: str | None = None


class SeriesCoverage(BaseModel):
    requested_points: int = Field(description="Number of points requested for the series.", examples=[252])
    returned_points: int = Field(description="Number of points returned for the series.", examples=[250])
    missing_points: int = Field(description="Number of missing points after applying policy.", examples=[2])
    coverage_ratio: Decimal = Field(
        description="Returned-to-requested coverage as a decimal ratio. Example: 0.992 means 99.2%.",
        examples=["0.992"],
    )


class SeriesGap(BaseModel):
    series_type: Literal["portfolio", "benchmark", "risk_free"] = Field(
        description="Series affected by the coverage gap."
    )
    from_date: dt_date = Field(description="Inclusive start date of the gap.", examples=["2026-02-10"])
    to_date: dt_date = Field(description="Inclusive end date of the gap.", examples=["2026-02-12"])
    gap_days: int = Field(description="Gap length in business dates after policy application.", examples=[3])


class ReturnsDiagnostics(BaseModel):
    coverage: SeriesCoverage = Field(description="Coverage summary for the response series.")
    gaps: list[SeriesGap] = Field(default_factory=list, description="Explicit coverage gaps retained in diagnostics.")
    policy_applied: DataPolicy = Field(description="Resolved data-policy settings used for the request.")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal diagnostic warnings for the response.")


class ReturnsProvenance(BaseModel):
    input_mode: InputMode = Field(description="Resolved returns-series input mode.", examples=["stateful"])
    input_fingerprint: str = Field(description="Canonical fingerprint of the executed inputs.")
    calculation_hash: str = Field(description="Canonical calculation hash for the executed payload.")


class ReturnsMetadata(BaseModel):
    generated_at: dt_datetime = Field(description="UTC timestamp at which the response was generated.")
    correlation_id: str | None = Field(
        default=None, description="Optional correlation identifier propagated through the request."
    )
    request_id: str | None = Field(
        default=None, description="Optional request identifier propagated through the request."
    )
    trace_id: str | None = Field(default=None, description="Optional distributed trace identifier.")


class ReturnsSeriesPayload(BaseModel):
    portfolio_returns: list[ReturnPoint] = Field(description="Portfolio point returns as decimal ratios.")
    cumulative_portfolio_returns: list[ReturnPoint] | None = Field(
        default=None,
        description="Cumulative linked portfolio returns as decimal ratios.",
    )
    benchmark_returns: list[ReturnPoint] | None = Field(
        default=None,
        description="Benchmark point returns as decimal ratios.",
    )
    cumulative_benchmark_returns: list[ReturnPoint] | None = Field(
        default=None,
        description="Cumulative linked benchmark returns as decimal ratios.",
    )
    risk_free_returns: list[ReturnPoint] | None = Field(
        default=None,
        description="Risk-free point returns as decimal ratios.",
    )
    cumulative_risk_free_returns: list[ReturnPoint] | None = Field(
        default=None,
        description="Cumulative linked risk-free returns as decimal ratios.",
    )
    active_returns: list[ReturnPoint] | None = Field(
        default=None,
        description="Arithmetic active return points as decimal ratios.",
    )
    cumulative_active_returns: list[ReturnPoint] | None = Field(
        default=None,
        description="Cumulative arithmetic active returns as decimal ratios, equal to cumulative portfolio minus cumulative benchmark.",
    )


class ReturnsSeriesBenchmarkContext(BaseModel):
    benchmark_id: str = Field(description="Resolved benchmark identifier.", examples=["BMK_GLOBAL_60_40"])
    return_source: BenchmarkReturnSource = Field(
        description="Resolved benchmark return source.", examples=["calculated"]
    )


class ReturnsSeriesResponse(BaseModel):
    calculation_id: UUID = Field(description="Stable calculation handle for this returns-series request.")
    source_service: Literal["lotus-performance"] = Field(
        default="lotus-performance",
        description="Service that generated the response.",
    )
    contract_version: str = Field(default="v1", description="Public response contract version.")
    portfolio_id: str = Field(description="Portfolio identifier.", examples=["PORTFOLIO_001"])
    as_of_date: dt_date = Field(description="As-of date used to resolve the request window.", examples=["2026-02-27"])
    frequency: ReturnsFrequency = Field(description="Output sampling frequency for the series.")
    metric_basis: MetricBasis = Field(description="Metric basis used for the returns series.")
    resolved_window: ResolvedWindow = Field(description="Resolved start/end dates for the response window.")
    benchmark_context: ReturnsSeriesBenchmarkContext | None = Field(
        default=None,
        description="Resolved benchmark context when benchmark returns were included.",
    )
    series: ReturnsSeriesPayload = Field(
        description="Returns-series payload. All return points in this payload are decimal ratios, not percentage-point values."
    )
    provenance: ReturnsProvenance = Field(description="Canonical provenance for the executed request.")
    diagnostics: ReturnsDiagnostics = Field(description="Coverage and policy diagnostics for the response.")
    metadata: ReturnsMetadata = Field(description="Operational metadata for the response.")


class ReturnsSeriesAcceptedResponse(BaseModel):
    calculation_id: UUID
    source_service: Literal["lotus-performance"] = "lotus-performance"
    contract_version: str = "v1"
    execution_mode: Literal["async"] = "async"
    status: Literal["pending"] = "pending"
    poll_path: str
    result_path: str
