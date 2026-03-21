from __future__ import annotations

from datetime import date as dt_date
from typing import Dict, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.responses import ComparativeAnalyticsBlock
from core.envelope import Audit, Diagnostics, Meta


class DailyBenchmarkReturn(BaseModel):
    date: dt_date = Field(description="Business date for this benchmark return observation.", examples=["2026-03-20"])
    benchmark_return: float = Field(
        description="Benchmark return for the date in percentage-point output units.",
        examples=[0.42],
    )
    cumulative_return: float = Field(
        description="Cumulative linked benchmark return through the date in percentage-point output units.",
        examples=[2.18],
    )
    benchmark_return_local: float | None = Field(
        default=None,
        description="Local-market component of the daily benchmark return in percentage points.",
        examples=[0.35],
    )
    benchmark_return_fx: float | None = Field(
        default=None,
        description="FX component of the daily benchmark return in percentage points.",
        examples=[0.07],
    )


class DailyBenchmarkComponentContribution(BaseModel):
    date: dt_date = Field(description="Business date for this component observation.", examples=["2026-03-20"])
    component_id: str = Field(description="Benchmark component identifier.", examples=["IDX_SP500_TR"])
    component_currency: str | None = Field(
        default=None,
        description="Native component currency when the component is currency-aware.",
        examples=["USD"],
    )
    weight_bop: float = Field(
        description="Beginning-of-day benchmark weight as a decimal ratio. Example: 0.60 means 60%.",
        examples=[0.6],
    )
    component_return: float = Field(
        description="Component return for the date in percentage-point output units.",
        examples=[0.55],
    )
    component_return_local: float | None = Field(
        default=None,
        description="Local-market component return in percentage points.",
        examples=[0.48],
    )
    component_return_fx: float | None = Field(
        default=None,
        description="FX component return in percentage points.",
        examples=[0.07],
    )
    contribution: float = Field(
        description="Total benchmark contribution from the component in percentage points.",
        examples=[0.33],
    )
    local_contribution: float | None = Field(
        default=None,
        description="Local-market benchmark contribution from the component in percentage points.",
        examples=[0.29],
    )
    fx_contribution: float | None = Field(
        default=None,
        description="FX benchmark contribution from the component in percentage points.",
        examples=[0.04],
    )


class SinglePeriodBenchmarkResult(BaseModel):
    benchmark: ComparativeAnalyticsBlock = Field(
        description="Benchmark summary and breakdowns for the period in percentage-point output units."
    )
    daily_returns: List[DailyBenchmarkReturn] | None = Field(
        default=None,
        description="Optional daily benchmark return ladder in percentage-point output units.",
    )
    component_contributions: List[DailyBenchmarkComponentContribution] | None = Field(
        default=None,
        description="Optional component-level benchmark contribution detail in percentage-point output units.",
    )


class BenchmarkPerformanceResponse(BaseModel):
    calculation_id: UUID = Field(description="Stable calculation handle for this benchmark request.")
    benchmark_id: str = Field(description="Resolved benchmark identifier.", examples=["BMK_GLOBAL_60_40"])
    benchmark_currency: str = Field(description="Benchmark base currency.", examples=["USD"])
    input_mode: BenchmarkInputMode = Field(
        default=BenchmarkInputMode.STATELESS,
        description="Resolved benchmark input mode.",
    )
    return_source: BenchmarkReturnSource = Field(
        default=BenchmarkReturnSource.CALCULATED,
        description="Resolved source of benchmark returns.",
    )
    results_by_period: Dict[str, SinglePeriodBenchmarkResult] = Field(
        description="Per-period benchmark outputs. All benchmark returns and contributions are emitted in percentage-point output units."
    )
    meta: Meta = Field(description="Shared metadata envelope for the calculation.")
    diagnostics: Diagnostics = Field(description="Diagnostic details for the calculation.")
    audit: Audit = Field(description="Audit details for the calculation.")

    model_config = ConfigDict(extra="forbid")


class BenchmarkAcceptedResponse(BaseModel):
    calculation_id: UUID
    poll_path: str
    result_path: str

    model_config = ConfigDict(extra="forbid")
