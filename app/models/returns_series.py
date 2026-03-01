from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime as dt_datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
        description="Simple period return value in decimal form (for example 0.0012 = 12 bps).",
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
    benchmark_series_ref: str | None = None


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
    consumer_system: str = Field(
        default="lotus-performance",
        description="Consumer system used for stateful upstream retrieval policy and lineage.",
        examples=["lotus-performance"],
    )


class ReturnsSeriesRequest(BaseModel):
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
        return self


class ResolvedWindow(BaseModel):
    start_date: dt_date
    end_date: dt_date
    resolved_period_label: str | None = None


class SeriesCoverage(BaseModel):
    requested_points: int
    returned_points: int
    missing_points: int
    coverage_ratio: Decimal


class SeriesGap(BaseModel):
    series_type: Literal["portfolio", "benchmark", "risk_free"]
    from_date: dt_date
    to_date: dt_date
    gap_days: int


class ReturnsDiagnostics(BaseModel):
    coverage: SeriesCoverage
    gaps: list[SeriesGap] = Field(default_factory=list)
    policy_applied: DataPolicy
    warnings: list[str] = Field(default_factory=list)


class ReturnsProvenance(BaseModel):
    input_mode: InputMode
    input_fingerprint: str
    calculation_hash: str


class ReturnsMetadata(BaseModel):
    generated_at: dt_datetime
    correlation_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None


class ReturnsSeriesPayload(BaseModel):
    portfolio_returns: list[ReturnPoint]
    benchmark_returns: list[ReturnPoint] | None = None
    risk_free_returns: list[ReturnPoint] | None = None


class ReturnsSeriesResponse(BaseModel):
    source_service: Literal["lotus-performance"] = "lotus-performance"
    contract_version: str = "v1"
    portfolio_id: str
    as_of_date: dt_date
    frequency: ReturnsFrequency
    metric_basis: MetricBasis
    resolved_window: ResolvedWindow
    series: ReturnsSeriesPayload
    provenance: ReturnsProvenance
    diagnostics: ReturnsDiagnostics
    metadata: ReturnsMetadata
