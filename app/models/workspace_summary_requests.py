from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.benchmark_analytics_requests import (
    BenchmarkInputMode,
    BenchmarkReturnSource,
    BenchmarkStatefulInput,
    BenchmarkStatelessInput,
)
from app.models.mwr_requests import Solver
from app.models.requests import DailyInputData
from app.models.twr_requests import TWRInputMode, TWRStatefulInput, TWRStatelessInput
from common.enums import Frequency
from core.envelope import Annualization, Calendar, FXRequestBlock, Output
from core.workspace_periods import WorkspacePeriodType

WORKSPACE_SUMMARY_REQUEST_EXAMPLES = [
    {
        "calculation_id": "0d000001-1111-4222-8333-abcdefabcdef",
        "input_mode": "stateless",
        "portfolio_id": "WORKSPACE_SUMMARY_01",
        "report_end_date": "2026-03-31",
        "performance_start_date": "2025-12-31",
        "periods": [
            {"period": "1M", "frequencies": ["daily", "monthly"]},
            {"period": "YTD", "frequencies": ["monthly"]},
            {"period": "1Y", "frequencies": ["monthly", "yearly"]},
        ],
        "include_benchmark": True,
        "stateless_input": {
            "valuation_points": [
                {"perf_date": "2026-01-02", "begin_mv": 1000000.0, "end_mv": 1008500.0},
                {
                    "perf_date": "2026-02-27",
                    "begin_mv": 1008500.0,
                    "bod_cf": 25000.0,
                    "end_mv": 1039500.0,
                },
                {
                    "perf_date": "2026-03-31",
                    "begin_mv": 1039500.0,
                    "eod_cf": -5000.0,
                    "mgmt_fees": -350.0,
                    "end_mv": 1054100.0,
                },
            ]
        },
        "benchmark": {
            "benchmark_id": "BMK_GLOBAL_60_40",
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2026-01-02", "benchmark_return": 0.0065},
                    {"perf_date": "2026-02-27", "benchmark_return": 0.011},
                    {"perf_date": "2026-03-31", "benchmark_return": 0.009},
                ],
            },
        },
    },
    {
        "calculation_id": "0d000002-1111-4222-8333-abcdefabcdef",
        "input_mode": "stateful",
        "portfolio_id": "WORKSPACE_SUMMARY_STATEFUL_01",
        "report_end_date": "2026-03-31",
        "periods": [
            {"period": "1M", "frequencies": ["daily", "monthly"]},
            {"period": "YTD", "frequencies": ["monthly"]},
            {"period": "SI", "frequencies": ["monthly", "yearly"]},
        ],
        "stateful_input": {},
        "include_benchmark": True,
        "benchmark": {"input_mode": "stateful", "stateful_input": {}},
        "report_ccy": "USD",
        "currency_mode": "BASE_ONLY",
    },
]


class WorkspaceSummaryPeriodRequest(BaseModel):
    period: WorkspacePeriodType = Field(..., description="Workspace horizon to calculate.", examples=["YTD"])
    frequencies: list[Frequency] = Field(
        ...,
        description="Breakdown frequencies to emit for this workspace horizon.",
        examples=[["daily", "monthly"]],
        json_schema_extra={"example": ["daily", "monthly"]},
    )

    @field_validator("frequencies")
    @classmethod
    def frequencies_must_not_be_empty(cls, value: list[Frequency]) -> list[Frequency]:
        if not value:
            raise ValueError("frequencies list cannot be empty for a workspace horizon")
        return value


class WorkspaceBenchmarkRequest(BaseModel):
    benchmark_id: str | None = Field(
        default=None,
        description="Benchmark identifier. Optional in stateful mode when lotus-core assignment should be resolved.",
        examples=["BMK_PB_GLOBAL_BALANCED_60_40"],
    )
    input_mode: BenchmarkInputMode = Field(
        default=BenchmarkInputMode.STATEFUL,
        description="Execution mode for benchmark analytics requested alongside the workspace summary.",
        examples=["stateful"],
    )
    return_source: BenchmarkReturnSource = Field(
        default=BenchmarkReturnSource.CALCULATED,
        description="Benchmark return source mode.",
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

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "WorkspaceBenchmarkRequest":
        if self.input_mode == BenchmarkInputMode.STATELESS:
            if self.stateless_input is None:
                raise ValueError("benchmark.stateless_input is required when benchmark.input_mode=stateless")
            if self.stateful_input is not None:
                raise ValueError("benchmark.stateful_input must be null when benchmark.input_mode=stateless")
            if not self.benchmark_id:
                raise ValueError("benchmark.benchmark_id is required when benchmark.input_mode=stateless")
        else:
            if self.stateful_input is None:
                self.stateful_input = BenchmarkStatefulInput()
            if self.stateless_input is not None:
                raise ValueError("benchmark.stateless_input must be null when benchmark.input_mode=stateful")
        return self


class WorkspaceSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": WORKSPACE_SUMMARY_REQUEST_EXAMPLES})

    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="Durable workspace summary calculation handle. If omitted, lotus-performance generates one.",
    )
    portfolio_id: str = Field(..., description="Portfolio identifier for the workspace.")
    report_end_date: date = Field(
        ...,
        description="Anchor end date for all requested workspace horizons.",
        examples=["2026-04-10"],
    )
    report_start_date: date | None = Field(
        default=None,
        description="Explicit start date used only when requested periods include EXPLICIT.",
        examples=["2026-01-01"],
    )
    performance_start_date: date | None = Field(
        default=None,
        description=(
            "Portfolio inception or earliest date for which performance data is available. "
            "In stateful mode lotus-performance can derive this upstream."
        ),
        examples=["2026-01-01"],
    )
    periods: list[WorkspaceSummaryPeriodRequest] = Field(
        ...,
        description="Requested workspace horizons and their breakdown frequencies.",
        examples=[[{"period": "YTD", "frequencies": ["daily", "monthly"]}]],
        json_schema_extra={"example": [{"period": "YTD", "frequencies": ["daily", "monthly"]}]},
    )
    input_mode: TWRInputMode = Field(
        default=TWRInputMode.STATELESS,
        description="Execution mode for the portfolio analytics used by the workspace summary.",
        examples=["stateful"],
    )
    stateless_input: TWRStatelessInput | None = Field(
        default=None,
        description="Stateless portfolio valuation observations. Preferred for new stateless integrations.",
    )
    stateful_input: TWRStatefulInput | None = Field(
        default=None,
        description="Required empty envelope for stateful source-owned workspace summaries.",
    )
    valuation_points: list[DailyInputData] = Field(
        default_factory=list,
        description="Deprecated compatibility stateless valuation input payload. Prefer stateless_input for new integrations.",
    )
    include_benchmark: bool = Field(
        default=False,
        description="Whether benchmark and active summary blocks should be returned.",
        examples=[True],
    )
    benchmark: WorkspaceBenchmarkRequest | None = Field(
        default=None,
        description="Optional benchmark request resolved and calculated alongside the workspace summary.",
    )
    mwr_method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"] = Field(
        default="XIRR",
        description="Money-weighted return method used for the MWR block.",
        examples=["XIRR"],
    )
    solver: Solver = Field(default_factory=Solver, description="Numerical solver settings for the MWR block.")
    currency: str = Field("USD", description="The three-letter ISO currency code for the request.", examples=["USD"])
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = Field(
        "FLOAT64",
        description="Numerical precision mode for the workspace summary.",
        examples=["FLOAT64"],
    )
    rounding_precision: int = Field(
        6,
        description="Number of decimal places to round float outputs to.",
        examples=[6],
    )
    calendar: Calendar = Field(default_factory=Calendar, description="Calendar settings for the workspace summary.")
    annualization: Annualization = Field(
        default_factory=lambda: Annualization(enabled=True, basis="ACT/365"),
        description="Annualization settings for workspace returns.",
    )
    output: Output = Field(default_factory=Output, description="Output toggles for optional workspace payload detail.")
    report_ccy: str | None = Field(
        default=None,
        description="Optional reporting currency used for stateful retrieval and output context.",
        examples=["USD"],
    )
    currency_mode: Literal["BASE_ONLY", "LOCAL_ONLY", "BOTH"] | None = Field(
        default=None,
        description="Optional multi-currency mode for the portfolio path.",
        examples=["BASE_ONLY"],
    )
    fx: FXRequestBlock | None = Field(
        default=None,
        description="Optional FX inputs used when currency_mode requires explicit FX data.",
    )

    @field_validator("periods")
    @classmethod
    def periods_must_not_be_empty(
        cls, value: list[WorkspaceSummaryPeriodRequest]
    ) -> list[WorkspaceSummaryPeriodRequest]:
        if not value:
            raise ValueError("periods list cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_mode_payloads(self) -> "WorkspaceSummaryRequest":
        requested_periods = {item.period for item in self.periods}
        if WorkspacePeriodType.EXPLICIT in requested_periods and self.report_start_date is None:
            raise ValueError("report_start_date is required when periods include EXPLICIT")

        if self.input_mode == TWRInputMode.STATELESS:
            has_nested = self.stateless_input is not None
            has_legacy = bool(self.valuation_points)
            if self.performance_start_date is None:
                raise ValueError("performance_start_date is required when input_mode=stateless")
            if has_nested and has_legacy:
                raise ValueError("Provide either stateless_input or valuation_points, not both, for stateless mode")
            if not has_nested and not has_legacy:
                raise ValueError("stateless_input or valuation_points is required when input_mode=stateless")
            if self.stateful_input is not None:
                raise ValueError("stateful_input must be null when input_mode=stateless")
        else:
            if self.stateful_input is None:
                raise ValueError("stateful_input is required when input_mode=stateful")
            if self.stateless_input is not None:
                raise ValueError("stateless_input must be null when input_mode=stateful")
            if self.valuation_points:
                raise ValueError("valuation_points must be null when input_mode=stateful")

        if self.benchmark is not None:
            self.include_benchmark = True
        if self.include_benchmark and self.input_mode == TWRInputMode.STATELESS and self.benchmark is None:
            raise ValueError("benchmark configuration is required when include_benchmark=true in stateless mode")

        return self

    def resolved_stateless_valuation_points(self) -> list[DailyInputData]:
        if self.stateless_input is not None:
            return self.stateless_input.valuation_points
        return self.valuation_points
