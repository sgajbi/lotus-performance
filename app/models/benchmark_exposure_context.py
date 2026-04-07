from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime as dt_datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.returns_series import ReturnsFrequency


class BenchmarkExposureGroupingDimension(str, Enum):
    POSITION = "POSITION"
    SECTOR = "SECTOR"
    ASSET_CLASS = "ASSET_CLASS"
    ISSUER = "ISSUER"


class BenchmarkExposureWindow(BaseModel):
    start_date: dt_date = Field(description="Inclusive start date for benchmark exposure history.", examples=["2026-01-02"])
    end_date: dt_date = Field(description="Inclusive end date for benchmark exposure history.", examples=["2026-02-28"])

    @model_validator(mode="after")
    def validate_range(self) -> "BenchmarkExposureWindow":
        if self.start_date > self.end_date:
            raise ValueError("window.start_date cannot be after window.end_date")
        return self


class BenchmarkExposurePageRequest(BaseModel):
    page_size: int = Field(
        default=1000,
        ge=1,
        le=1000,
        description="Maximum number of exposure rows to return. Capped at 1000 to match lotus-core benchmark market-series contract.",
        examples=[1000],
    )
    page_token: str | None = Field(
        default=None,
        description="Opaque pagination token from a previous benchmark exposure context response.",
        examples=["1000"],
    )


class BenchmarkExposureContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this benchmark exposure context request.",
    )
    portfolio_id: str = Field(
        description="Portfolio identifier used to resolve benchmark assignment when benchmark_id is omitted.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    benchmark_id: str | None = Field(
        default=None,
        description="Optional explicit benchmark identifier. If omitted, lotus-performance resolves the benchmark assignment through lotus-core.",
        examples=["BMK_PB_GLOBAL_BALANCED_60_40"],
    )
    as_of_date: dt_date = Field(
        description="As-of date used for benchmark assignment and exposure context resolution.",
        examples=["2026-02-28"],
    )
    window: BenchmarkExposureWindow = Field(description="Date window for exposure history.")
    frequency: ReturnsFrequency = Field(
        default=ReturnsFrequency.DAILY,
        description="Output frequency for benchmark exposure context. v1 supports DAILY.",
    )
    reporting_currency: str | None = Field(
        default=None,
        description="Optional reporting currency used to request currency-aligned benchmark market-series context.",
        examples=["USD"],
    )
    grouping_dimensions: list[BenchmarkExposureGroupingDimension] = Field(
        default_factory=lambda: [BenchmarkExposureGroupingDimension.POSITION],
        description="Benchmark exposure grouping dimensions to return. v1 supports POSITION, SECTOR, and ASSET_CLASS. ISSUER remains gated until issuer benchmark semantics are approved.",
        examples=[["POSITION", "SECTOR", "ASSET_CLASS"]],
        json_schema_extra={"example": ["POSITION", "SECTOR", "ASSET_CLASS"]},
    )
    page: BenchmarkExposurePageRequest = Field(default_factory=BenchmarkExposurePageRequest)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "BenchmarkExposureContextRequest":
        if not self.grouping_dimensions:
            raise ValueError("grouping_dimensions must contain at least one value")
        unsupported = sorted({dimension.value for dimension in self.grouping_dimensions if dimension == BenchmarkExposureGroupingDimension.ISSUER})
        if unsupported:
            raise ValueError("benchmark exposure context does not yet support grouping_dimensions=" + ", ".join(unsupported))
        return self


class BenchmarkExposureRow(BaseModel):
    valuation_date: dt_date = Field(description="Observation date for the benchmark exposure row.", examples=["2026-01-02"])
    component_id: str | None = Field(
        default=None,
        description="Benchmark component identifier when the row represents POSITION-level exposure; null for aggregated groups.",
        examples=["IDX_GLOBAL_EQUITY"],
    )
    grouping_dimension: BenchmarkExposureGroupingDimension = Field(description="Grouping dimension represented by this exposure row.")
    group_key: str = Field(description="Stable canonical group key for this benchmark exposure row.", examples=["ASSET_CLASS_EQUITY"])
    group_label: str = Field(description="Human-readable group label for this benchmark exposure row.", examples=["Equity"])
    weight: Decimal = Field(
        description="Benchmark exposure weight as a decimal fraction. Example: 0.60 means 60%.",
        examples=["0.600000"],
    )


class BenchmarkExposurePageResponse(BaseModel):
    next_page_token: str | None = Field(
        default=None,
        description="Token for the next page, or null when all exposure rows have been returned.",
    )


class BenchmarkExposureMetadata(BaseModel):
    source_system: Literal["lotus-core"] = Field(
        default="lotus-core",
        description="Authoritative source system for benchmark composition and classifications.",
    )
    served_by: Literal["lotus-performance"] = Field(
        default="lotus-performance",
        description="Service exposing the performance-aligned benchmark exposure context view.",
    )
    calculation_run_id: UUID = Field(description="lotus-performance request/calc identifier for this exposure context response.")
    contract_version: Literal["v1"] = Field(default="v1", description="Contract version for this response payload.")
    generated_at: dt_datetime = Field(description="UTC timestamp at which the response was generated.")
    retrieval_metadata: dict[str, int] = Field(
        default_factory=dict,
        description="Upstream retrieval counters such as chunk and page counts.",
        examples=[{"benchmark_market_series_chunk_count": 1, "index_catalog_page_count": 1}],
    )


class BenchmarkExposureContextResponse(BaseModel):
    calculation_id: UUID = Field(description="Stable calculation handle for this benchmark exposure context request.")
    source_service: Literal["lotus-performance"] = Field(default="lotus-performance")
    contract_version: Literal["v1"] = Field(default="v1")
    portfolio_id: str = Field(description="Portfolio identifier used for request context.", examples=["PB_SG_GLOBAL_BAL_001"])
    benchmark_id: str = Field(description="Resolved benchmark identifier.", examples=["BMK_PB_GLOBAL_BALANCED_60_40"])
    benchmark_version: str = Field(description="Benchmark version/effective as-of marker used for the exposure context.", examples=["2026-02-28"])
    as_of_date: dt_date = Field(description="As-of date used for context resolution.", examples=["2026-02-28"])
    window: BenchmarkExposureWindow = Field(description="Resolved benchmark exposure context window.")
    frequency: ReturnsFrequency = Field(description="Frequency of the exposure context rows.")
    reporting_currency: str | None = Field(default=None, description="Reporting currency used for the exposure context.")
    rows: list[BenchmarkExposureRow] = Field(description="Benchmark exposure rows aligned to benchmark return context.")
    page: BenchmarkExposurePageResponse = Field(description="Pagination metadata for exposure rows.")
    metadata: BenchmarkExposureMetadata = Field(description="Lineage and operational metadata for the response.")
