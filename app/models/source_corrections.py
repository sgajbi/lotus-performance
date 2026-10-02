from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceAuthorizationEvidence(BaseModel):
    issuer: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1, max_length=255)

    @field_validator("issuer", "evidence_id", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SourceCorrectionRequest(BaseModel):
    correction_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    source_product: Literal["portfolio_timeseries", "benchmark_returns", "fx_rates"]
    source_revision: str = Field(min_length=1, max_length=255)
    supersedes_source_revision: str | None = Field(default=None, min_length=1, max_length=255)
    target_type: Literal["portfolio", "benchmark"]
    target_id: str = Field(min_length=1, max_length=255)
    effective_start_date: date
    effective_end_date: date
    observed_at_utc: datetime
    correction_reason: str = Field(min_length=1, max_length=500)
    source_authorization: SourceAuthorizationEvidence

    @field_validator(
        "correction_id",
        "source_revision",
        "supersedes_source_revision",
        "target_id",
        "correction_reason",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("observed_at_utc")
    @classmethod
    def require_utc_observation(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None:
            raise ValueError("observed_at_utc must include a UTC offset")
        if offset.total_seconds() != 0:
            raise ValueError("observed_at_utc must use UTC")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> "SourceCorrectionRequest":
        if self.effective_end_date < self.effective_start_date:
            raise ValueError("effective_end_date must be on or after effective_start_date")
        expected_target = {
            "portfolio_timeseries": "portfolio",
            "benchmark_returns": "benchmark",
        }.get(self.source_product)
        if expected_target is not None and self.target_type != expected_target:
            raise ValueError(f"{self.source_product} corrections require target_type={expected_target}")
        return self


class SourceCorrectionImpact(BaseModel):
    original_calculation_id: UUID
    corrected_calculation_id: UUID
    analytics_type: str
    state: Literal["pending", "running", "complete", "failed"]
    original_result_path: str
    corrected_result_path: str
    original_calculation_hash: str | None = None
    corrected_calculation_hash: str | None = None
    original_response_fingerprint: str | None = None
    corrected_response_fingerprint: str | None = None
    output_changed: bool | None = None
    failure_code: str | None = None


class SourceCorrectionResponse(BaseModel):
    correction_id: str
    source_product: str
    source_revision: str
    target_type: str
    target_id: str
    effective_start_date: date
    effective_end_date: date
    coalesced_effective_start_date: date
    coalesced_effective_end_date: date
    observed_at_utc: datetime
    state: Literal["no_effect", "recalculation_pending", "complete", "partial_failure", "superseded", "cancelled"]
    replayed: bool = False
    affected_calculation_count: int = Field(ge=0)
    impacts: list[SourceCorrectionImpact] = Field(default_factory=list)
    current_result_paths: list[str] = Field(default_factory=list)
    coverage_limits: list[str] = Field(default_factory=list)


class RetainedCalculationResult(BaseModel):
    calculation_id: UUID
    analytics_type: str
    calculation_hash: str | None
    input_fingerprint: str | None
    response: dict
