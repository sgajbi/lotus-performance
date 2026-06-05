from __future__ import annotations

from datetime import date as dt_date
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import Analysis
from core.envelope import Annualization, Calendar, Output
from core.periods import PeriodType


class BenchmarkInputMode(str, Enum):
    STATELESS = "stateless"
    STATEFUL = "stateful"


class BenchmarkReturnSource(str, Enum):
    CALCULATED = "calculated"
    VENDOR_SERIES = "vendor_series"


class BenchmarkComponentObservationInput(BaseModel):
    component_id: str = Field(..., description="Benchmark component identifier.", examples=["IDX_SP500_TR"])
    perf_date: dt_date = Field(
        ...,
        description="Benchmark observation date in YYYY-MM-DD format.",
        examples=["2026-01-02"],
    )
    weight_bop: float = Field(
        ...,
        description="Beginning-of-day component benchmark weight as a decimal ratio.",
        examples=[0.6],
    )
    component_currency: str | None = Field(
        default=None,
        description="Optional benchmark component currency.",
        examples=["USD"],
    )
    component_return: float = Field(
        ...,
        description="Component daily return expressed as a decimal fraction (0.01 = 1%).",
        examples=[0.0125],
    )
    component_return_local: float | None = Field(
        default=None,
        description="Optional component daily local return expressed as a decimal fraction.",
        examples=[0.01],
    )
    component_return_fx: float | None = Field(
        default=None,
        description="Optional component daily FX return expressed as a decimal fraction.",
        examples=[0.002475],
    )

    model_config = ConfigDict(extra="forbid")


class BenchmarkComponentPricePointInput(BaseModel):
    component_id: str = Field(..., description="Benchmark component identifier.", examples=["IDX_EUROSTOXX_TR"])
    perf_date: dt_date = Field(
        ...,
        description="Benchmark price observation date in YYYY-MM-DD format.",
        examples=["2026-01-02"],
    )
    weight_bop: float = Field(
        ...,
        description="Beginning-of-day component benchmark weight as a decimal ratio.",
        examples=[0.4],
    )
    index_price: float = Field(
        ...,
        description="Component price or index level observed on the benchmark date.",
        examples=[101.25],
    )
    component_currency: str | None = Field(
        default=None,
        description="Optional component currency for the price observation.",
        examples=["EUR"],
    )
    fx_rate_to_benchmark: float | None = Field(
        default=None,
        description="Optional FX rate used to normalize the component price into benchmark currency.",
        examples=[1.212],
    )

    model_config = ConfigDict(extra="forbid")


class BenchmarkReturnPointInput(BaseModel):
    perf_date: dt_date = Field(
        ...,
        description="Benchmark return observation date in YYYY-MM-DD format.",
        examples=["2026-01-02"],
    )
    benchmark_return: float = Field(
        ...,
        description="Benchmark daily return expressed as a decimal fraction (0.01 = 1%).",
        examples=[0.0042],
    )

    model_config = ConfigDict(extra="forbid")


class BenchmarkStatelessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_currency: str = Field(
        ...,
        description="Benchmark currency as a three-letter ISO code, for example USD.",
        examples=["USD"],
    )
    component_observations: list[BenchmarkComponentObservationInput] = Field(
        default_factory=list,
        description="Daily benchmark component return observations used when return_source=calculated.",
    )
    component_price_points: list[BenchmarkComponentPricePointInput] = Field(
        default_factory=list,
        description="Daily benchmark component price observations used to derive returns when return_source=calculated.",
    )
    benchmark_return_points: list[BenchmarkReturnPointInput] = Field(
        default_factory=list,
        description="Daily benchmark return observations used only when return_source=vendor_series.",
    )


class BenchmarkStatefulInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_benchmark_analysis_selection(analyses: list[Analysis], report_start_date: dt_date | None) -> None:
    if not analyses:
        raise ValueError("analyses list cannot be empty")
    if any(analysis.period == PeriodType.EXPLICIT for analysis in analyses) and report_start_date is None:
        raise ValueError("report_start_date is required when analyses include EXPLICIT")


def _validate_calculated_stateless_benchmark_payload(stateless_input: BenchmarkStatelessInput) -> None:
    has_component_observations = bool(stateless_input.component_observations)
    has_component_price_points = bool(stateless_input.component_price_points)
    if has_component_observations == has_component_price_points:
        raise ValueError(
            "exactly one of stateless_input.component_observations or "
            "stateless_input.component_price_points is required when return_source=calculated"
        )
    if stateless_input.benchmark_return_points:
        raise ValueError("stateless_input.benchmark_return_points must be empty when return_source=calculated")


def _validate_vendor_series_stateless_benchmark_payload(stateless_input: BenchmarkStatelessInput) -> None:
    if not stateless_input.benchmark_return_points:
        raise ValueError("stateless_input.benchmark_return_points are required when return_source=vendor_series")
    if stateless_input.component_observations:
        raise ValueError("stateless_input.component_observations must be empty when return_source=vendor_series")
    if stateless_input.component_price_points:
        raise ValueError("stateless_input.component_price_points must be empty when return_source=vendor_series")


def _validate_stateless_benchmark_payloads(
    *,
    stateless_input: BenchmarkStatelessInput | None,
    stateful_input: BenchmarkStatefulInput | None,
    return_source: BenchmarkReturnSource,
) -> None:
    if stateless_input is None:
        raise ValueError("stateless_input is required when input_mode=stateless")
    if stateful_input is not None:
        raise ValueError("stateful_input must be null when input_mode=stateless")
    if return_source == BenchmarkReturnSource.CALCULATED:
        _validate_calculated_stateless_benchmark_payload(stateless_input)
    else:
        _validate_vendor_series_stateless_benchmark_payload(stateless_input)


def _validate_stateful_benchmark_payloads(
    *,
    stateless_input: BenchmarkStatelessInput | None,
    stateful_input: BenchmarkStatefulInput | None,
) -> None:
    if stateful_input is None:
        raise ValueError("stateful_input is required when input_mode=stateful")
    if stateless_input is not None:
        raise ValueError("stateless_input must be null when input_mode=stateful")


class BenchmarkAnalyticsRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "input_mode": "stateless",
                    "benchmark_id": "BMK_GLOBAL_60_40",
                    "benchmark_start_date": "2026-01-02",
                    "report_end_date": "2026-01-03",
                    "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
                    "return_source": "calculated",
                    "output": {"include_timeseries": True},
                    "stateless_input": {
                        "benchmark_currency": "USD",
                        "component_observations": [
                            {
                                "component_id": "IDX_SP500_TR",
                                "perf_date": "2026-01-02",
                                "weight_bop": 0.6,
                                "component_return": 0.01,
                            }
                        ],
                    },
                },
                {
                    "input_mode": "stateful",
                    "benchmark_id": "BMK_PB_GLOBAL_BALANCED_60_40",
                    "benchmark_start_date": "2026-01-01",
                    "report_end_date": "2026-04-10",
                    "analyses": [{"period": "YTD", "frequencies": ["daily", "monthly"]}],
                    "return_source": "calculated",
                    "stateful_input": {},
                },
            ]
        },
    )

    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="Durable benchmark calculation handle. If omitted, lotus-performance generates one.",
    )
    benchmark_id: str = Field(..., description="Benchmark identifier.", examples=["BMK_PB_GLOBAL_BALANCED_60_40"])
    benchmark_start_date: dt_date = Field(
        ...,
        description="Earliest date for which benchmark data is available for the request.",
        examples=["2026-01-01"],
    )
    report_start_date: dt_date | None = Field(
        default=None,
        description="Explicit start date used only when analyses include the EXPLICIT period.",
        examples=["2026-03-01"],
    )
    report_end_date: dt_date = Field(
        ...,
        description="Anchor end date for relative-period resolution.",
        examples=["2026-04-10"],
    )
    analyses: list[Analysis] = Field(..., description="Requested benchmark period analyses.")
    input_mode: BenchmarkInputMode = Field(
        default=BenchmarkInputMode.STATELESS,
        description="Execution mode for benchmark analytics. Use stateless for caller-supplied input and stateful for lotus-core-sourced input.",
        examples=["stateful"],
    )
    return_source: BenchmarkReturnSource = Field(
        default=BenchmarkReturnSource.CALCULATED,
        description="Benchmark return source mode. Calculated derives returns from components; vendor_series uses authored benchmark return points.",
        examples=["calculated"],
    )
    stateless_input: BenchmarkStatelessInput | None = Field(
        default=None,
        description="Stateless benchmark input payload.",
    )
    stateful_input: BenchmarkStatefulInput | None = Field(
        default=None,
        description="Stateful benchmark input payload resolved through lotus-core integrations.",
    )
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = Field(
        "FLOAT64",
        description="Numerical precision mode for benchmark calculations.",
        examples=["FLOAT64"],
    )
    rounding_precision: int = Field(6, description="Number of decimal places to round float outputs to.", examples=[6])
    calendar: Calendar = Field(
        default_factory=Calendar, description="Calendar settings applied during benchmark analytics."
    )
    annualization: Annualization = Field(
        default_factory=Annualization,
        description="Annualization settings applied to benchmark analytics outputs.",
    )
    output: Output = Field(
        default_factory=Output, description="Output toggles controlling optional benchmark payload sections."
    )

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "BenchmarkAnalyticsRequest":
        _validate_benchmark_analysis_selection(self.analyses, self.report_start_date)
        if self.input_mode == BenchmarkInputMode.STATELESS:
            _validate_stateless_benchmark_payloads(
                stateless_input=self.stateless_input,
                stateful_input=self.stateful_input,
                return_source=self.return_source,
            )
        else:
            _validate_stateful_benchmark_payloads(
                stateless_input=self.stateless_input,
                stateful_input=self.stateful_input,
            )
        return self

    def to_benchmark_performance_request(
        self,
        *,
        benchmark_currency: str,
        component_observations: list[dict[str, object]] | None = None,
        benchmark_return_points: list[dict[str, object]] | None = None,
    ) -> BenchmarkPerformanceRequest:
        payload = self.model_dump(
            exclude={"input_mode", "stateless_input", "stateful_input"},
            mode="python",
        )
        payload["benchmark_currency"] = benchmark_currency
        if component_observations is not None:
            payload["component_observations"] = component_observations
        elif self.stateless_input is not None:
            payload["component_observations"] = [
                point.model_dump(mode="python") for point in self.stateless_input.component_observations
            ]
        else:
            payload["component_observations"] = []

        if benchmark_return_points is not None:
            payload["benchmark_return_points"] = benchmark_return_points
        elif self.stateless_input is not None:
            payload["benchmark_return_points"] = [
                point.model_dump(mode="python") for point in self.stateless_input.benchmark_return_points
            ]
        else:
            payload["benchmark_return_points"] = []
        return BenchmarkPerformanceRequest.model_validate(payload)
