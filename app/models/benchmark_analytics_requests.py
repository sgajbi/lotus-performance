from __future__ import annotations

from datetime import date as dt_date
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import Analysis
from core.envelope import Annualization, Calendar, Output


class BenchmarkInputMode(str, Enum):
    STATELESS = "stateless"
    STATEFUL = "stateful"


class BenchmarkReturnSource(str, Enum):
    CALCULATED = "calculated"
    VENDOR_SERIES = "vendor_series"


class BenchmarkComponentObservationInput(BaseModel):
    component_id: str = Field(..., description="Benchmark component identifier.")
    perf_date: dt_date = Field(
        ...,
        description="Benchmark observation date in YYYY-MM-DD format.",
    )
    weight_bop: float = Field(..., description="Beginning-of-day component benchmark weight.")
    component_currency: str | None = Field(
        default=None,
        description="Optional benchmark component currency.",
    )
    component_return: float = Field(
        ...,
        description="Component daily return expressed as a decimal fraction (0.01 = 1%).",
    )
    component_return_local: float | None = Field(
        default=None,
        description="Optional component daily local return expressed as a decimal fraction.",
    )
    component_return_fx: float | None = Field(
        default=None,
        description="Optional component daily FX return expressed as a decimal fraction.",
    )

    model_config = ConfigDict(extra="forbid")


class BenchmarkComponentPricePointInput(BaseModel):
    component_id: str = Field(..., description="Benchmark component identifier.")
    perf_date: dt_date = Field(
        ...,
        description="Benchmark price observation date in YYYY-MM-DD format.",
    )
    weight_bop: float = Field(..., description="Beginning-of-day component benchmark weight.")
    index_price: float = Field(
        ...,
        description="Component price or index level observed on the benchmark date.",
    )
    component_currency: str | None = Field(
        default=None,
        description="Optional component currency for the price observation.",
    )
    fx_rate_to_benchmark: float | None = Field(
        default=None,
        description="Optional FX rate used to normalize the component price into benchmark currency.",
    )

    model_config = ConfigDict(extra="forbid")


class BenchmarkReturnPointInput(BaseModel):
    perf_date: dt_date = Field(
        ...,
        description="Benchmark return observation date in YYYY-MM-DD format.",
    )
    benchmark_return: float = Field(
        ...,
        description="Benchmark daily return expressed as a decimal fraction (0.01 = 1%).",
    )

    model_config = ConfigDict(extra="forbid")


class BenchmarkStatelessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_currency: str = Field(..., description="Benchmark currency as a three-letter ISO code, for example USD.")
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


class BenchmarkAnalyticsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="Durable benchmark calculation handle. If omitted, lotus-performance generates one.",
    )
    benchmark_id: str = Field(..., description="Benchmark identifier.")
    benchmark_start_date: dt_date = Field(
        ...,
        description="Earliest date for which benchmark data is available for the request.",
    )
    report_end_date: dt_date = Field(
        ...,
        description="Anchor end date for relative-period resolution.",
    )
    analyses: list[Analysis] = Field(..., description="Requested benchmark period analyses.")
    input_mode: BenchmarkInputMode = Field(
        default=BenchmarkInputMode.STATELESS,
        description="Execution mode for benchmark analytics.",
    )
    return_source: BenchmarkReturnSource = Field(
        default=BenchmarkReturnSource.CALCULATED,
        description="Benchmark return source mode.",
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
    )
    rounding_precision: int = Field(6, description="Number of decimal places to round float outputs to.")
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
        if not self.analyses:
            raise ValueError("analyses list cannot be empty")
        if self.input_mode == BenchmarkInputMode.STATELESS:
            if self.stateless_input is None:
                raise ValueError("stateless_input is required when input_mode=stateless")
            if self.stateful_input is not None:
                raise ValueError("stateful_input must be null when input_mode=stateless")
            if self.return_source == BenchmarkReturnSource.CALCULATED:
                has_component_observations = bool(self.stateless_input.component_observations)
                has_component_price_points = bool(self.stateless_input.component_price_points)
                if has_component_observations == has_component_price_points:
                    raise ValueError(
                        "exactly one of stateless_input.component_observations or "
                        "stateless_input.component_price_points is required when return_source=calculated"
                    )
                if self.stateless_input.benchmark_return_points:
                    raise ValueError(
                        "stateless_input.benchmark_return_points must be empty when return_source=calculated"
                    )
            else:
                if not self.stateless_input.benchmark_return_points:
                    raise ValueError(
                        "stateless_input.benchmark_return_points are required when return_source=vendor_series"
                    )
                if self.stateless_input.component_observations:
                    raise ValueError(
                        "stateless_input.component_observations must be empty when return_source=vendor_series"
                    )
                if self.stateless_input.component_price_points:
                    raise ValueError(
                        "stateless_input.component_price_points must be empty when return_source=vendor_series"
                    )
        else:
            if self.stateful_input is None:
                raise ValueError("stateful_input is required when input_mode=stateful")
            if self.stateless_input is not None:
                raise ValueError("stateless_input must be null when input_mode=stateful")
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
