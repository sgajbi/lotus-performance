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
    valuation_points: list[DailyInputData] = Field(
        ...,
        description="Canonical stateless portfolio valuation observations ordered by perf_date. day sequence is derived server-side.",
    )


class TWRStatefulInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_calculated_stateless_twr_benchmark_payload(request: "TWRBenchmarkRequest") -> None:
    if request.stateless_input is None:
        return

    has_component_observations = bool(request.stateless_input.component_observations)
    has_component_price_points = bool(request.stateless_input.component_price_points)
    if has_component_observations == has_component_price_points:
        raise ValueError(
            "exactly one of benchmark.stateless_input.component_observations or "
            "benchmark.stateless_input.component_price_points is required when "
            "benchmark.return_source=calculated"
        )
    if request.stateless_input.benchmark_return_points:
        raise ValueError(
            "benchmark.stateless_input.benchmark_return_points must be empty when benchmark.return_source=calculated"
        )


def _validate_vendor_series_stateless_twr_benchmark_payload(request: "TWRBenchmarkRequest") -> None:
    if request.stateless_input is None:
        return

    if not request.stateless_input.benchmark_return_points:
        raise ValueError(
            "benchmark.stateless_input.benchmark_return_points are required when benchmark.return_source=vendor_series"
        )
    if request.stateless_input.component_observations:
        raise ValueError(
            "benchmark.stateless_input.component_observations must be empty when benchmark.return_source=vendor_series"
        )
    if request.stateless_input.component_price_points:
        raise ValueError(
            "benchmark.stateless_input.component_price_points must be empty when benchmark.return_source=vendor_series"
        )


def _validate_stateless_twr_benchmark_payloads(request: "TWRBenchmarkRequest") -> None:
    if request.stateless_input is None:
        raise ValueError("benchmark.stateless_input is required when benchmark.input_mode=stateless")
    if request.stateful_input is not None:
        raise ValueError("benchmark.stateful_input must be null when benchmark.input_mode=stateless")
    if not request.benchmark_id:
        raise ValueError("benchmark.benchmark_id is required when benchmark.input_mode=stateless")
    if request.return_source == BenchmarkReturnSource.CALCULATED:
        _validate_calculated_stateless_twr_benchmark_payload(request)
    else:
        _validate_vendor_series_stateless_twr_benchmark_payload(request)


def _validate_stateful_twr_benchmark_payloads(request: "TWRBenchmarkRequest") -> None:
    if request.stateful_input is None:
        raise ValueError("benchmark.stateful_input is required when benchmark.input_mode=stateful")
    if request.stateless_input is not None:
        raise ValueError("benchmark.stateless_input must be null when benchmark.input_mode=stateful")


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
            _validate_stateless_twr_benchmark_payloads(self)
        else:
            _validate_stateful_twr_benchmark_payloads(self)
        return self


class TWRResolvedExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio: PerformanceRequest = Field(
        ..., description="Resolved stateless portfolio request executed by the TWR engine."
    )
    benchmark: BenchmarkPerformanceRequest | None = Field(
        default=None,
        description="Resolved benchmark request executed alongside portfolio TWR when benchmark inclusion is enabled.",
    )


def _has_legacy_twr_valuation_points(request: "TWRAnalyticsRequest") -> bool:
    return len(request.valuation_points) > 0


def _has_nested_twr_stateless_input(request: "TWRAnalyticsRequest") -> bool:
    return request.stateless_input is not None


def _has_exactly_one_stateless_twr_payload(request: "TWRAnalyticsRequest") -> bool:
    return _has_nested_twr_stateless_input(request) != _has_legacy_twr_valuation_points(request)


def _validate_stateless_twr_payloads(request: "TWRAnalyticsRequest") -> None:
    if request.performance_start_date is None:
        raise ValueError("performance_start_date is required when input_mode=stateless")
    if not _has_exactly_one_stateless_twr_payload(request):
        has_nested = _has_nested_twr_stateless_input(request)
        has_legacy = _has_legacy_twr_valuation_points(request)
        if not has_nested and not has_legacy:
            raise ValueError("stateless_input or valuation_points is required when input_mode=stateless")
        raise ValueError("Provide either stateless_input or valuation_points, not both, for stateless mode")
    if request.stateful_input is not None:
        raise ValueError("stateful_input must be null when input_mode=stateless")


def _validate_stateful_twr_payloads(request: "TWRAnalyticsRequest") -> None:
    if request.stateful_input is None:
        raise ValueError("stateful_input is required when input_mode=stateful")
    if request.stateless_input is not None:
        raise ValueError("stateless_input must be null when input_mode=stateful")
    if request.valuation_points:
        raise ValueError("valuation_points must be null when input_mode=stateful")


def _validate_twr_benchmark_inclusion(request: "TWRAnalyticsRequest") -> None:
    if request.benchmark is not None and not request.include_benchmark:
        request.include_benchmark = True
    if request.include_benchmark and request.input_mode == TWRInputMode.STATELESS and request.benchmark is None:
        raise ValueError("benchmark configuration is required when include_benchmark=true in stateless mode")


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
        description="Legacy stateless valuation input payload using the same canonical valuation-point shape. Prefer stateless_input for new integrations.",
    )

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "TWRAnalyticsRequest":
        if self.input_mode == TWRInputMode.STATELESS:
            _validate_stateless_twr_payloads(self)
        if self.input_mode == TWRInputMode.STATEFUL:
            _validate_stateful_twr_payloads(self)
        _validate_twr_benchmark_inclusion(self)
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
