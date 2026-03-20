from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.benchmark_analytics_requests import (
    BenchmarkInputMode,
    BenchmarkReturnSource,
    BenchmarkStatefulInput,
    BenchmarkStatelessInput,
)
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import DailyInputData, PerformanceRequest, PerformanceRequestBase


class TWRInputMode(str, Enum):
    STATELESS = "stateless"
    STATEFUL = "stateful"


class TWRStatelessInput(BaseModel):
    valuation_points: list[DailyInputData]


class TWRStatefulInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TWRBenchmarkRequest(BaseModel):
    benchmark_id: str | None = Field(
        default=None,
        description="Benchmark identifier. Optional in stateful mode when benchmark assignment should be sourced from lotus-core.",
    )
    input_mode: BenchmarkInputMode = Field(
        default=BenchmarkInputMode.STATEFUL,
        description="Execution mode for benchmark analytics requested alongside TWR.",
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

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "TWRBenchmarkRequest":
        if self.input_mode == BenchmarkInputMode.STATELESS:
            if self.stateless_input is None:
                raise ValueError("benchmark.stateless_input is required when benchmark.input_mode=stateless")
            if self.stateful_input is not None:
                raise ValueError("benchmark.stateful_input must be null when benchmark.input_mode=stateless")
            if not self.benchmark_id:
                raise ValueError("benchmark.benchmark_id is required when benchmark.input_mode=stateless")
            if self.return_source == BenchmarkReturnSource.CALCULATED:
                has_component_observations = bool(self.stateless_input.component_observations)
                has_component_price_points = bool(self.stateless_input.component_price_points)
                if has_component_observations == has_component_price_points:
                    raise ValueError(
                        "exactly one of benchmark.stateless_input.component_observations or "
                        "benchmark.stateless_input.component_price_points is required when "
                        "benchmark.return_source=calculated"
                    )
                if self.stateless_input.benchmark_return_points:
                    raise ValueError(
                        "benchmark.stateless_input.benchmark_return_points must be empty when benchmark.return_source=calculated"
                    )
            else:
                if not self.stateless_input.benchmark_return_points:
                    raise ValueError(
                        "benchmark.stateless_input.benchmark_return_points are required when benchmark.return_source=vendor_series"
                    )
                if self.stateless_input.component_observations:
                    raise ValueError(
                        "benchmark.stateless_input.component_observations must be empty when benchmark.return_source=vendor_series"
                    )
                if self.stateless_input.component_price_points:
                    raise ValueError(
                        "benchmark.stateless_input.component_price_points must be empty when benchmark.return_source=vendor_series"
                    )
        else:
            if self.stateful_input is None:
                raise ValueError("benchmark.stateful_input is required when benchmark.input_mode=stateful")
            if self.stateless_input is not None:
                raise ValueError("benchmark.stateless_input must be null when benchmark.input_mode=stateful")
        return self


class TWRResolvedExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio: PerformanceRequest
    benchmark: BenchmarkPerformanceRequest | None = None


class TWRAnalyticsRequest(PerformanceRequestBase):
    performance_start_date: date | None = Field(
        default=None,
        description=(
            "Portfolio inception or earliest performance date. Required in stateless mode. "
            "In stateful mode lotus-performance derives the authoritative start date from lotus-core."
        ),
    )
    include_benchmark: bool = Field(
        default=False,
        description="Whether benchmark performance should be calculated and returned alongside portfolio TWR.",
    )
    input_mode: TWRInputMode = Field(
        default=TWRInputMode.STATELESS,
        description="Execution mode for TWR analytics.",
        examples=["stateful"],
    )
    stateless_input: TWRStatelessInput | None = Field(
        default=None,
        description="Stateless TWR input payload.",
    )
    stateful_input: TWRStatefulInput | None = Field(
        default=None,
        description="Stateful TWR input payload resolved through lotus-core integrations.",
    )
    benchmark: TWRBenchmarkRequest | None = Field(
        default=None,
        description="Optional benchmark request resolved and calculated alongside portfolio TWR.",
    )
    valuation_points: list[DailyInputData] = Field(
        default_factory=list,
        description="Legacy stateless valuation input payload. Prefer stateless_input for new integrations.",
    )

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "TWRAnalyticsRequest":
        if self.input_mode == TWRInputMode.STATELESS:
            has_nested = self.stateless_input is not None
            has_legacy = len(self.valuation_points) > 0
            if self.performance_start_date is None:
                raise ValueError("performance_start_date is required when input_mode=stateless")
            if has_nested and has_legacy:
                raise ValueError("Provide either stateless_input or valuation_points, not both, for stateless mode")
            if not has_nested and not has_legacy:
                raise ValueError("stateless_input or valuation_points is required when input_mode=stateless")
            if self.stateful_input is not None:
                raise ValueError("stateful_input must be null when input_mode=stateless")
        if self.input_mode == TWRInputMode.STATEFUL:
            if self.stateful_input is None:
                raise ValueError("stateful_input is required when input_mode=stateful")
            if self.stateless_input is not None:
                raise ValueError("stateless_input must be null when input_mode=stateful")
            if self.valuation_points:
                raise ValueError("valuation_points must be null when input_mode=stateful")
        if self.benchmark is not None and not self.include_benchmark:
            self.include_benchmark = True
        if self.include_benchmark and self.input_mode == TWRInputMode.STATELESS and self.benchmark is None:
            raise ValueError("benchmark configuration is required when include_benchmark=true in stateless mode")
        return self

    def to_stateless_performance_request(
        self, *, valuation_points: list[DailyInputData] | None = None
    ) -> PerformanceRequest:
        if self.performance_start_date is None:
            raise ValueError("performance_start_date is required to build a stateless PerformanceRequest")
        if valuation_points is not None:
            resolved_points = valuation_points
        elif self.stateless_input is not None:
            resolved_points = self.stateless_input.valuation_points
        elif self.valuation_points:
            resolved_points = self.valuation_points
        else:
            raise ValueError("No stateless valuation_points are available to build a PerformanceRequest")

        payload = self.model_dump(
            exclude={
                "input_mode",
                "stateless_input",
                "stateful_input",
                "benchmark",
                "include_benchmark",
                "valuation_points",
            },
            mode="python",
        )
        payload["valuation_points"] = [point.model_dump(mode="python") for point in resolved_points]
        return PerformanceRequest.model_validate(payload)
