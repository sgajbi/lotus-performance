from __future__ import annotations

from datetime import date as dt_date
from typing import Dict, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.async_polling import DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS
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
    calculation_id: UUID = Field(
        description="Stable calculation handle for this benchmark request.",
        examples=["f7f7b0f2-8f9a-4a99-bad1-d16f51b0c111"],
    )
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

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "calculation_id": "f7f7b0f2-8f9a-4a99-bad1-d16f51b0c111",
                    "benchmark_id": "BMK_PB_GLOBAL_BALANCED_60_40",
                    "benchmark_currency": "USD",
                    "input_mode": "stateful",
                    "return_source": "calculated",
                    "results_by_period": {
                        "YTD": {
                            "benchmark": {
                                "summary": {
                                    "period_return": {"base": 1.24},
                                    "cumulative_return": {"base": 1.24},
                                },
                                "breakdowns": {},
                                "benchmark_id": "BMK_PB_GLOBAL_BALANCED_60_40",
                                "benchmark_currency": "USD",
                                "input_mode": "stateful",
                                "return_source": "calculated",
                            }
                        }
                    },
                    "meta": {
                        "calculation_id": "f7f7b0f2-8f9a-4a99-bad1-d16f51b0c111",
                        "engine_version": "0.1.0",
                        "precision_mode": "FLOAT64",
                        "calendar": {"type": "BUSINESS", "trading_calendar": "NYSE"},
                        "annualization": {"enabled": False, "basis": "BUS/252"},
                        "periods": {
                            "requested": ["YTD"],
                            "master_start": "2026-01-01",
                            "master_end": "2026-04-10",
                        },
                        "input_fingerprint": "sha256:example",
                        "calculation_hash": "sha256:example",
                        "report_ccy": "USD",
                    },
                    "diagnostics": {
                        "nip_days": 0,
                        "reset_days": 0,
                        "effective_period_start": "2026-01-01",
                        "notes": [],
                    },
                    "audit": {
                        "residual_applied_bp": 0.0,
                        "counts": {
                            "component_observations": 250,
                            "benchmark_return_points": 0,
                            "daily_returns": 100,
                        },
                    },
                }
            ]
        },
    )


class BenchmarkAcceptedResponse(BaseModel):
    calculation_id: UUID = Field(
        description="Stable calculation handle for the accepted benchmark request.",
        examples=["f7f7b0f2-8f9a-4a99-bad1-d16f51b0c111"],
    )
    poll_path: str = Field(
        description="Execution lifecycle path to poll while benchmark work is running.",
        examples=["/performance/executions/f7f7b0f2-8f9a-4a99-bad1-d16f51b0c111"],
    )
    result_path: str = Field(
        description="Benchmark result path to read once execution completes.",
        examples=["/performance/benchmark/results/f7f7b0f2-8f9a-4a99-bad1-d16f51b0c111"],
    )
    recommended_poll_after_seconds: int = Field(
        default=DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS,
        description="Recommended minimum seconds to wait before polling poll_path or result_path again.",
        examples=[DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS],
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "calculation_id": "f7f7b0f2-8f9a-4a99-bad1-d16f51b0c111",
                    "poll_path": "/performance/executions/f7f7b0f2-8f9a-4a99-bad1-d16f51b0c111",
                    "result_path": "/performance/benchmark/results/f7f7b0f2-8f9a-4a99-bad1-d16f51b0c111",
                    "recommended_poll_after_seconds": DEFAULT_RECOMMENDED_POLL_AFTER_SECONDS,
                }
            ]
        },
    )
