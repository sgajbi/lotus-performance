from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime as dt_datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar, Literal
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
    ONE_YEAR = "1Y"
    THREE_YEAR = "3Y"
    FIVE_YEAR = "5Y"
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
    PERIOD_ALIASES: ClassVar[dict[str, str]] = {
        "ONE_YEAR": "1Y",
        "THREE_YEAR": "3Y",
        "FIVE_YEAR": "5Y",
        "ITD": "SI",
    }

    mode: ReturnsWindowMode = Field(
        description=(
            "Window-resolution mode. Use EXPLICIT when the caller owns the exact observation dates; "
            "use RELATIVE for period-to-date windows resolved from as_of_date."
        ),
        examples=["EXPLICIT"],
    )
    from_date: dt_date | None = Field(
        default=None,
        description="Inclusive start date when mode=EXPLICIT.",
        examples=["2026-01-01"],
    )
    to_date: dt_date | None = Field(
        default=None,
        description="Inclusive end date when mode=EXPLICIT.",
        examples=["2026-04-10"],
    )
    period: ReturnsRelativePeriod | None = Field(
        default=None,
        description=(
            "Relative period label when mode=RELATIVE. Prefer canonical values MTD, QTD, "
            "YTD, 1Y, 3Y, 5Y, SI, and YEAR. Legacy aliases ONE_YEAR, THREE_YEAR, "
            "FIVE_YEAR, and ITD are accepted and normalized."
        ),
        examples=["3Y"],
    )
    year: int | None = Field(
        default=None,
        description="Calendar year when period=YEAR.",
        examples=[2026],
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_period_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            period = data.get("period")
            if isinstance(period, str):
                normalized_period = cls.PERIOD_ALIASES.get(period, period)
                if normalized_period != period:
                    return {**data, "period": normalized_period}
        return data

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
    include_portfolio: bool = Field(
        default=True,
        description="Whether to return portfolio returns. This should normally stay true for downstream analytics.",
        examples=[True],
    )
    include_benchmark: bool = Field(
        default=False,
        description=(
            "Whether to include benchmark, cumulative benchmark, active, and cumulative active series. "
            "Stateful mode resolves the benchmark assignment unless benchmark.benchmark_id is supplied."
        ),
        examples=[True],
    )
    include_risk_free: bool = Field(
        default=False,
        description="Whether to include risk-free point and cumulative return series.",
        examples=[False],
    )


class BenchmarkSpec(BaseModel):
    benchmark_id: str | None = Field(
        default=None,
        description=(
            "Optional stateful benchmark override. Leave null to resolve the portfolio benchmark assignment from "
            "lotus-core. Not meaningful in stateless mode."
        ),
        examples=["BMK_PB_GLOBAL_BALANCED_60_40"],
    )
    return_source: BenchmarkReturnSource = Field(
        default=BenchmarkReturnSource.CALCULATED,
        description=(
            "Stateful benchmark sourcing mode. calculated uses the lotus-performance benchmark engine; "
            "vendor_series explicitly asks lotus-core for stored benchmark returns."
        ),
        examples=["calculated"],
    )


class RiskFreeSpec(BaseModel):
    rate_series_ref: str | None = Field(
        default=None,
        description="Optional risk-free series reference retained for caller lineage. Stateful sourcing uses reporting_currency.",
        examples=["USD_SOFR"],
    )
    day_count_basis: DayCountBasis | None = Field(
        default=None,
        description="Optional day-count basis for risk-free lineage. Returned values are already period returns.",
        examples=["ACT_365"],
    )


class DataPolicy(BaseModel):
    missing_data_policy: MissingDataPolicy = Field(
        default=MissingDataPolicy.FAIL_FAST,
        description=(
            "Policy for missing observations. FAIL_FAST rejects missing portfolio coverage; ALLOW_PARTIAL emits "
            "coverage diagnostics; STRICT_INTERSECTION keeps only dates common to selected series."
        ),
        examples=["ALLOW_PARTIAL"],
    )
    fill_method: FillMethod = Field(
        default=FillMethod.NONE,
        description="Optional fill method applied to selected benchmark/risk-free side series before alignment.",
        examples=["NONE"],
    )
    calendar_policy: CalendarPolicy = Field(
        default=CalendarPolicy.BUSINESS,
        description="Calendar used to estimate requested coverage points for diagnostics.",
        examples=["BUSINESS"],
    )
    max_gap_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        description="Optional caller tolerance for retained gap diagnostics. Reserved for future enforcement.",
        examples=[5],
    )


class StatelessInput(BaseModel):
    portfolio_returns: list[ReturnPoint] = Field(
        description="Caller-supplied portfolio point returns as decimal ratios for stateless mode."
    )
    benchmark_returns: list[ReturnPoint] | None = Field(
        default=None,
        description="Caller-supplied benchmark point returns as decimal ratios when include_benchmark=true.",
    )
    risk_free_returns: list[ReturnPoint] | None = Field(
        default=None,
        description="Caller-supplied risk-free point returns as decimal ratios when include_risk_free=true.",
    )


class StatefulInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_returns_series_input_envelopes(
    *,
    input_mode: InputMode,
    stateless_input: StatelessInput | None,
    stateful_input: StatefulInput | None,
) -> None:
    if input_mode == InputMode.STATELESS and stateless_input is None:
        raise ValueError("stateless_input is required when input_mode=stateless")
    if input_mode == InputMode.STATEFUL and stateful_input is None:
        raise ValueError("stateful_input is required when input_mode=stateful")
    if input_mode == InputMode.STATELESS and stateful_input is not None:
        raise ValueError("stateful_input must be null when input_mode=stateless")
    if input_mode == InputMode.STATEFUL and stateless_input is not None:
        raise ValueError("stateless_input must be null when input_mode=stateful")


def _validate_returns_series_stateless_selection_inputs(
    *,
    input_mode: InputMode,
    series_selection: SeriesSelection,
    stateless_input: StatelessInput | None,
) -> None:
    if input_mode != InputMode.STATELESS:
        return
    if series_selection.include_benchmark and (not stateless_input or not stateless_input.benchmark_returns):
        raise ValueError("benchmark_returns are required when include_benchmark=true in stateless mode")
    if series_selection.include_risk_free and (not stateless_input or not stateless_input.risk_free_returns):
        raise ValueError("risk_free_returns are required when include_risk_free=true in stateless mode")


def _validate_returns_series_stateless_benchmark_override(
    *,
    input_mode: InputMode,
    benchmark: BenchmarkSpec | None,
) -> None:
    if input_mode != InputMode.STATELESS or benchmark is None:
        return
    if benchmark.benchmark_id is not None:
        raise ValueError("benchmark.benchmark_id is only supported in stateful mode for returns-series")
    if benchmark.return_source != BenchmarkReturnSource.CALCULATED:
        raise ValueError("benchmark.return_source is only supported in stateful mode for returns-series")


class ReturnsSeriesRequest(BaseModel):
    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this returns-series calculation request.",
    )
    portfolio_id: str = Field(description="Portfolio identifier.", examples=["DEMO_DPM_EUR_001"])
    as_of_date: dt_date = Field(description="As-of date for window resolution.", examples=["2026-02-27"])
    window: ReturnsWindow = Field(description="Requested measurement window.")
    frequency: ReturnsFrequency = Field(
        default=ReturnsFrequency.DAILY,
        description="Output sampling frequency. Weekly and monthly values are geometrically linked from daily points.",
        examples=["DAILY"],
    )
    metric_basis: MetricBasis = Field(
        default=MetricBasis.NET,
        description="Portfolio return basis. NET includes fee drag; GROSS neutralizes fees according to methodology.",
        examples=["NET"],
    )
    reporting_currency: str | None = Field(default=None, description="Target reporting currency.", examples=["USD"])
    series_selection: SeriesSelection = Field(
        default_factory=SeriesSelection,
        description="Controls which return families are included in the response.",
    )
    benchmark: BenchmarkSpec | None = Field(
        default=None,
        description="Optional stateful benchmark sourcing override.",
    )
    risk_free: RiskFreeSpec | None = Field(
        default=None,
        description="Optional risk-free lineage hint. Stateful risk-free sourcing is driven by reporting_currency.",
    )
    data_policy: DataPolicy = Field(default_factory=DataPolicy, description="Coverage and alignment policy.")
    input_mode: InputMode = Field(
        default=InputMode.STATELESS,
        description="stateless uses request-supplied return points; stateful sources portfolio and side series.",
        examples=["stateful"],
    )
    stateless_input: StatelessInput | None = Field(
        default=None,
        description="Required when input_mode=stateless. Must be omitted for stateful requests.",
    )
    stateful_input: StatefulInput | None = Field(
        default=None,
        description="Required empty envelope when input_mode=stateful. Source identity is stamped server-side.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "as_of_date": "2026-04-10",
                    "window": {"mode": "RELATIVE", "period": "YTD"},
                    "frequency": "DAILY",
                    "metric_basis": "NET",
                    "reporting_currency": "USD",
                    "series_selection": {
                        "include_portfolio": True,
                        "include_benchmark": True,
                        "include_risk_free": False,
                    },
                    "data_policy": {
                        "missing_data_policy": "ALLOW_PARTIAL",
                        "fill_method": "NONE",
                        "calendar_policy": "BUSINESS",
                    },
                    "input_mode": "stateful",
                    "stateful_input": {},
                }
            ]
        }
    )

    @model_validator(mode="after")
    def validate_selection(self) -> "ReturnsSeriesRequest":
        _validate_returns_series_input_envelopes(
            input_mode=self.input_mode,
            stateless_input=self.stateless_input,
            stateful_input=self.stateful_input,
        )
        _validate_returns_series_stateless_selection_inputs(
            input_mode=self.input_mode,
            series_selection=self.series_selection,
            stateless_input=self.stateless_input,
        )
        _validate_returns_series_stateless_benchmark_override(
            input_mode=self.input_mode,
            benchmark=self.benchmark,
        )
        return self


class ResolvedWindow(BaseModel):
    start_date: dt_date = Field(description="Inclusive resolved start date.", examples=["2026-01-01"])
    end_date: dt_date = Field(description="Inclusive resolved end date.", examples=["2026-04-10"])
    resolved_period_label: str | None = Field(
        default=None,
        description="Relative period label when the request used mode=RELATIVE.",
        examples=["YTD"],
    )


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
    calculation_id: UUID = Field(description="Stable calculation handle for the accepted async request.")
    source_service: Literal["lotus-performance"] = Field(
        default="lotus-performance",
        description="Service that accepted the async request.",
    )
    contract_version: str = Field(default="v1", description="Public response contract version.")
    execution_mode: Literal["async"] = Field(default="async", description="Execution mode for this accepted request.")
    status: Literal["pending"] = Field(default="pending", description="Current async result status.")
    poll_path: str = Field(
        description="Execution status path for polling progress and failure detail.",
        examples=["/performance/executions/f25cbd85-b7e5-4aaf-b994-ff59cb143ef5"],
    )
    result_path: str = Field(
        description="Endpoint-specific path for retrieving the final returns-series payload.",
        examples=["/integration/returns/series/results/f25cbd85-b7e5-4aaf-b994-ff59cb143ef5"],
    )
