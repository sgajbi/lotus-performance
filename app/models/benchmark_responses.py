from __future__ import annotations

from datetime import date as dt_date
from typing import Dict, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from core.envelope import Audit, Diagnostics, Meta


class DailyBenchmarkReturn(BaseModel):
    date: dt_date
    benchmark_return: float
    cumulative_return: float
    benchmark_return_local: float | None = None
    benchmark_return_fx: float | None = None


class DailyBenchmarkComponentContribution(BaseModel):
    date: dt_date
    component_id: str
    component_currency: str | None = None
    weight_bop: float
    component_return: float
    component_return_local: float | None = None
    component_return_fx: float | None = None
    contribution: float
    local_contribution: float | None = None
    fx_contribution: float | None = None


class SinglePeriodBenchmarkResult(BaseModel):
    benchmark_return: float
    daily_returns: List[DailyBenchmarkReturn] | None = None
    component_contributions: List[DailyBenchmarkComponentContribution] | None = None


class BenchmarkPerformanceResponse(BaseModel):
    calculation_id: UUID
    benchmark_id: str
    benchmark_currency: str
    input_mode: BenchmarkInputMode = BenchmarkInputMode.STATELESS
    return_source: BenchmarkReturnSource = BenchmarkReturnSource.CALCULATED
    results_by_period: Dict[str, SinglePeriodBenchmarkResult]
    meta: Meta
    diagnostics: Diagnostics
    audit: Audit

    model_config = ConfigDict(extra="forbid")


class BenchmarkAcceptedResponse(BaseModel):
    calculation_id: UUID
    poll_path: str
    result_path: str

    model_config = ConfigDict(extra="forbid")
