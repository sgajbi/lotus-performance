from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime as dt_datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.returns_series import ReturnsFrequency

_OPENAPI_ABSENT_PAGE_MARKER: str | None = None


class BenchmarkExposureGroupingDimension(str, Enum):
    POSITION = "POSITION"
    SECTOR = "SECTOR"
    ASSET_CLASS = "ASSET_CLASS"
    ISSUER = "ISSUER"


class BenchmarkExposureWindow(BaseModel):
    start_date: dt_date = Field(
        description="Inclusive start date for benchmark exposure history.", examples=["2026-01-02"]
    )
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
        description=(
            "Opaque source-bound continuation from the previous response. Historical numeric offset "
            "tokens remain readable for compatibility but cannot prove cross-page source consistency."
        ),
    )


class BenchmarkExposureContextRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "benchmark_id": "BMK_PB_GLOBAL_BALANCED_60_40",
                    "as_of_date": "2026-04-10",
                    "window": {"start_date": "2026-01-01", "end_date": "2026-04-10"},
                    "frequency": "DAILY",
                    "reporting_currency": "USD",
                    "grouping_dimensions": ["POSITION", "SECTOR", "ASSET_CLASS", "ISSUER"],
                    "page": {"page_size": 1000, "page_token": _OPENAPI_ABSENT_PAGE_MARKER},
                }
            ]
        },
    )

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
        description="Output frequency for benchmark exposure context. v1 supports DAILY only.",
        examples=["DAILY"],
    )
    reporting_currency: str | None = Field(
        default=None,
        description="Optional reporting currency used to request currency-aligned benchmark market-series context.",
        examples=["USD"],
    )
    grouping_dimensions: list[BenchmarkExposureGroupingDimension] = Field(
        default_factory=lambda: [BenchmarkExposureGroupingDimension.POSITION],
        description="Benchmark exposure grouping dimensions to return. v1 supports POSITION, SECTOR, ASSET_CLASS, and ISSUER. ISSUER groups are sourced from lotus-core index-catalog classification labels.",
        examples=[["POSITION", "SECTOR", "ASSET_CLASS", "ISSUER"]],
        json_schema_extra={"example": ["POSITION", "SECTOR", "ASSET_CLASS", "ISSUER"]},
    )
    page: BenchmarkExposurePageRequest = Field(default_factory=BenchmarkExposurePageRequest)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "BenchmarkExposureContextRequest":
        if self.frequency != ReturnsFrequency.DAILY:
            raise ValueError("benchmark exposure context v1 supports frequency=DAILY only")
        if not self.grouping_dimensions:
            raise ValueError("grouping_dimensions must contain at least one value")
        return self


class BenchmarkExposureRow(BaseModel):
    valuation_date: dt_date = Field(
        description="Observation date for the benchmark exposure row.", examples=["2026-01-02"]
    )
    component_id: str | None = Field(
        default=None,
        description="Benchmark component identifier when the row represents POSITION-level exposure; null for aggregated groups.",
        examples=["IDX_GLOBAL_EQUITY"],
    )
    grouping_dimension: BenchmarkExposureGroupingDimension = Field(
        description="Grouping dimension represented by this exposure row."
    )
    group_key: str = Field(
        description="Stable canonical group key for this benchmark exposure row.", examples=["ASSET_CLASS_EQUITY"]
    )
    group_label: str = Field(
        description="Human-readable group label for this benchmark exposure row.", examples=["Equity"]
    )
    weight: Decimal = Field(
        description="Benchmark exposure weight as a decimal fraction. Example: 0.60 means 60%.",
        examples=["0.600000"],
    )


class BenchmarkExposurePageResponse(BaseModel):
    next_page_token: str | None = Field(
        default=None,
        description="Token for the next page, or null when all exposure rows have been returned.",
    )
    continuation_consistency: Literal["source_bound", "legacy_offset_unbound"] = Field(
        description=(
            "source_bound continuations reject a changed economic source on later pages; "
            "legacy_offset_unbound identifies a caller-supplied numeric offset that cannot do so."
        ),
    )


BenchmarkExposureOmissionReason = Literal[
    "INVALID_COMPONENT_SHAPE",
    "MISSING_COMPONENT_ID",
    "INVALID_POINTS_SHAPE",
    "EMPTY_POINTS",
    "INVALID_POINT_SHAPE",
    "MISSING_SERIES_DATE",
    "INVALID_SERIES_DATE",
    "MISSING_COMPONENT_WEIGHT",
]


class BenchmarkExposureOmission(BaseModel):
    """One source component or point omitted from the derived exposure rows."""

    component_id: str | None = Field(
        default=None,
        description=(
            "Source component identity when it was safely usable for diagnosis; null when the "
            "source identity itself was unusable."
        ),
        examples=["IDX_GLOBAL_BONDS"],
    )
    series_date: dt_date | None = Field(
        default=None,
        description=(
            "Source observation date when it was safely parseable; null when the source date was missing or unusable."
        ),
        examples=["2026-01-02"],
    )
    reason_code: BenchmarkExposureOmissionReason = Field(
        description="Bounded reason why the supplied component or point could not form derived exposure evidence.",
        examples=["MISSING_COMPONENT_WEIGHT"],
    )


def _validate_complete_exposure_source_quality(quality: "BenchmarkExposureSourceQuality") -> None:
    if any(
        (
            quality.omitted_component_count,
            quality.omitted_point_count,
            quality.reason_codes,
            quality.omissions,
            quality.omissions_truncated,
        )
    ):
        raise ValueError("complete exposure_source_quality cannot contain omissions")


def _validate_incomplete_exposure_source_quality(quality: "BenchmarkExposureSourceQuality") -> None:
    _validate_incomplete_exposure_basics(quality)
    _validate_exposure_reason_codes(quality)
    _validate_exposure_omission_count(quality)
    _validate_exposure_omission_reasons(quality)


def _validate_incomplete_exposure_basics(quality: "BenchmarkExposureSourceQuality") -> None:
    if quality.omitted_component_count + quality.omitted_point_count == 0 or not quality.reason_codes:
        raise ValueError("incomplete exposure_source_quality requires omission counts and reason_codes")


def _validate_exposure_reason_codes(quality: "BenchmarkExposureSourceQuality") -> None:
    if quality.reason_codes != sorted(set(quality.reason_codes)):
        raise ValueError("exposure_source_quality reason_codes must be unique and sorted")


def _validate_exposure_omission_count(quality: "BenchmarkExposureSourceQuality") -> None:
    omitted_count = quality.omitted_component_count + quality.omitted_point_count
    if len(quality.omissions) > omitted_count:
        raise ValueError("exposure_source_quality omissions cannot exceed omitted source facts")
    if quality.omissions_truncated and len(quality.omissions) >= omitted_count:
        raise ValueError("truncated exposure_source_quality must omit at least one source fact")
    if not quality.omissions_truncated and len(quality.omissions) != omitted_count:
        raise ValueError("untruncated exposure_source_quality must list every omitted source fact")


def _validate_exposure_omission_reasons(quality: "BenchmarkExposureSourceQuality") -> None:
    if not {omission.reason_code for omission in quality.omissions}.issubset(quality.reason_codes):
        raise ValueError("exposure_source_quality omissions must use a declared reason_code")


class BenchmarkExposureSourceQuality(BaseModel):
    """Request-wide completeness posture for benchmark exposure source economics."""

    status: Literal["complete", "incomplete"] = Field(
        description=(
            "Complete when every supplied source component and point was usable for the derived "
            "exposure view; incomplete when any supplied source evidence was omitted."
        )
    )
    omitted_component_count: int = Field(
        ge=0,
        description=(
            "Number of supplied component objects omitted because their identity or point collection was unusable."
        ),
        examples=[1],
    )
    omitted_point_count: int = Field(
        ge=0,
        description=(
            "Number of supplied component points omitted because required exposure economics were missing or unusable."
        ),
        examples=[2],
    )
    reason_codes: list[BenchmarkExposureOmissionReason] = Field(
        default_factory=list,
        description="Sorted bounded reason codes covering all omitted source components and points.",
        examples=[["MISSING_COMPONENT_WEIGHT"]],
    )
    omissions: list[BenchmarkExposureOmission] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Bounded source-safe identities and dates for omitted evidence. This list is a "
            "diagnostic sample; counts and reason_codes remain complete when it is truncated."
        ),
    )
    omissions_truncated: bool = Field(
        default=False,
        description=(
            "Whether omissions exceeded the bounded diagnostic list while the omission counts "
            "and reason codes remain complete."
        ),
    )

    @model_validator(mode="after")
    def validate_completeness_evidence(self) -> "BenchmarkExposureSourceQuality":
        if self.status == "complete":
            _validate_complete_exposure_source_quality(self)
        else:
            _validate_incomplete_exposure_source_quality(self)
        return self


class BenchmarkExposureMetadata(BaseModel):
    source_system: Literal["lotus-core"] = Field(
        default="lotus-core",
        description="Authoritative source system for benchmark composition and classifications.",
    )
    served_by: Literal["lotus-performance"] = Field(
        default="lotus-performance",
        description="Service exposing the performance-aligned benchmark exposure context view.",
    )
    calculation_run_id: UUID = Field(
        description="lotus-performance request/calc identifier for this exposure context response."
    )
    contract_version: Literal["v1"] = Field(default="v1", description="Contract version for this response payload.")
    correlation_id: str = Field(
        description=(
            "Request correlation identifier carried as required trust metadata for downstream mesh consumers."
        ),
        examples=["corr_benchmark_exposure_001"],
    )
    generated_at: dt_datetime = Field(description="UTC timestamp at which the response was generated.")
    retrieval_metadata: dict[str, int] = Field(
        default_factory=dict,
        description="Upstream retrieval counters such as chunk and page counts.",
        examples=[{"benchmark_market_series_chunk_count": 1, "index_catalog_page_count": 1}],
    )
    retrieval_metadata_quality: dict[str, int | list[str] | Literal["valid", "degraded"]] = Field(
        default_factory=lambda: {"status": "valid", "warning_count": 0, "reason_codes": [], "invalid_fields": []},
        description=(
            "Source-safe quality summary for optional upstream retrieval telemetry. Malformed optional telemetry "
            "degrades the counters and records bounded reason codes without exposing raw upstream values."
        ),
        examples=[
            {
                "status": "degraded",
                "warning_count": 1,
                "reason_codes": ["MALFORMED_UPSTREAM_RETRIEVAL_METADATA_COUNT"],
                "invalid_fields": ["retrieval_metadata.chunk_count"],
            }
        ],
    )
    exposure_source_quality: BenchmarkExposureSourceQuality = Field(
        default_factory=lambda: BenchmarkExposureSourceQuality(
            status="complete",
            omitted_component_count=0,
            omitted_point_count=0,
        ),
        description=(
            "Request-wide economic completeness evidence for the derived exposure rows. It is "
            "separate from retrieval_metadata_quality, which describes optional telemetry only."
        ),
    )


class BenchmarkExposureContextResponse(BaseModel):
    calculation_id: UUID = Field(description="Stable calculation handle for this benchmark exposure context request.")
    source_service: Literal["lotus-performance"] = Field(
        default="lotus-performance",
        description="Service that owns and serves this performance-aligned benchmark exposure context.",
        examples=["lotus-performance"],
    )
    contract_version: Literal["v1"] = Field(
        default="v1",
        description="Version of the benchmark exposure context contract.",
        examples=["v1"],
    )
    portfolio_id: str = Field(
        description="Portfolio identifier used for request context.", examples=["PB_SG_GLOBAL_BAL_001"]
    )
    benchmark_id: str = Field(description="Resolved benchmark identifier.", examples=["BMK_PB_GLOBAL_BALANCED_60_40"])
    benchmark_version: str = Field(
        description="Benchmark version/effective as-of marker used for the exposure context.", examples=["2026-02-28"]
    )
    as_of_date: dt_date = Field(description="As-of date used for context resolution.", examples=["2026-02-28"])
    window: BenchmarkExposureWindow = Field(description="Resolved benchmark exposure context window.")
    frequency: ReturnsFrequency = Field(description="Frequency of the exposure context rows.")
    reporting_currency: str | None = Field(
        default=None, description="Reporting currency used for the exposure context."
    )
    rows: list[BenchmarkExposureRow] = Field(description="Benchmark exposure rows aligned to benchmark return context.")
    page: BenchmarkExposurePageResponse = Field(description="Pagination metadata for exposure rows.")
    metadata: BenchmarkExposureMetadata = Field(description="Lineage and operational metadata for the response.")

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "calculation_id": "0d000004-1111-4222-8333-abcdefabcdef",
                    "source_service": "lotus-performance",
                    "contract_version": "v1",
                    "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                    "benchmark_id": "BMK_PB_GLOBAL_BALANCED_60_40",
                    "benchmark_version": "2026-04-10",
                    "as_of_date": "2026-04-10",
                    "window": {"start_date": "2026-01-01", "end_date": "2026-04-10"},
                    "frequency": "DAILY",
                    "reporting_currency": "USD",
                    "rows": [
                        {
                            "valuation_date": "2026-04-10",
                            "component_id": "IDX_GLOBAL_EQUITY",
                            "grouping_dimension": "POSITION",
                            "group_key": "IDX_GLOBAL_EQUITY",
                            "group_label": "IDX_GLOBAL_EQUITY",
                            "weight": "0.600000",
                        }
                    ],
                    "page": {
                        "next_page_token": _OPENAPI_ABSENT_PAGE_MARKER,
                        "continuation_consistency": "source_bound",
                    },
                    "metadata": {
                        "source_system": "lotus-core",
                        "served_by": "lotus-performance",
                        "calculation_run_id": "0d000004-1111-4222-8333-abcdefabcdef",
                        "contract_version": "v1",
                        "correlation_id": "corr_benchmark_exposure_001",
                        "generated_at": "2026-04-10T00:00:00Z",
                        "retrieval_metadata": {
                            "benchmark_market_series_chunk_count": 1,
                            "benchmark_market_series_page_count": 1,
                            "index_catalog_page_count": 1,
                        },
                        "retrieval_metadata_quality": {
                            "status": "valid",
                            "warning_count": 0,
                            "reason_codes": [],
                            "invalid_fields": [],
                        },
                        "exposure_source_quality": {
                            "status": "complete",
                            "omitted_component_count": 0,
                            "omitted_point_count": 0,
                            "reason_codes": [],
                            "omissions": [],
                            "omissions_truncated": False,
                        },
                    },
                }
            ]
        },
    )
