from __future__ import annotations

from datetime import date as dt_date
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.requests import Analysis
from core.envelope import Annualization, Calendar, Output


class BenchmarkComponentObservation(BaseModel):
    component_id: str = Field(..., description="Benchmark component identifier.")
    perf_date: dt_date = Field(..., description="Benchmark observation date.")
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


class BenchmarkReturnPoint(BaseModel):
    perf_date: dt_date = Field(..., description="Benchmark return observation date.")
    benchmark_return: float = Field(
        ...,
        description="Benchmark daily return expressed as a decimal fraction (0.01 = 1%).",
    )

    model_config = ConfigDict(extra="forbid")


class BenchmarkPerformanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(default_factory=uuid4)
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
    return_source: Literal["calculated", "vendor_series"] = Field(
        default="calculated",
        description="Benchmark return source mode.",
    )
    benchmark_currency: str = Field(..., description="Benchmark currency.")
    component_observations: list[BenchmarkComponentObservation] = Field(default_factory=list)
    benchmark_return_points: list[BenchmarkReturnPoint] = Field(default_factory=list)
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = Field(
        "FLOAT64",
        description="Numerical precision mode for benchmark calculations.",
    )
    rounding_precision: int = Field(6, description="Number of decimal places to round float outputs to.")
    calendar: Calendar = Field(default_factory=Calendar)
    annualization: Annualization = Field(default_factory=Annualization)
    output: Output = Field(default_factory=Output)

    @model_validator(mode="after")
    def validate_source_payloads(self) -> "BenchmarkPerformanceRequest":
        if not self.analyses:
            raise ValueError("analyses list cannot be empty")

        if self.return_source == "calculated":
            if not self.component_observations:
                raise ValueError(
                    "component_observations are required when return_source=calculated"
                )
            if self.benchmark_return_points:
                raise ValueError(
                    "benchmark_return_points must be empty when return_source=calculated"
                )
        else:
            if not self.benchmark_return_points:
                raise ValueError(
                    "benchmark_return_points are required when return_source=vendor_series"
                )
            if self.component_observations:
                raise ValueError(
                    "component_observations must be empty when return_source=vendor_series"
                )
        return self
