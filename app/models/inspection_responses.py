from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.inspection_requests import TWRInspectionProfile, TWRInspectionSubjectType


class TWRInspectionVerdict(StrEnum):
    SUPPORTABLE = "supportable"
    SUPPORTABLE_WITH_WARNINGS = "supportable_with_warnings"
    NOT_SUPPORTABLE = "not_supportable"
    INSPECTION_FAILED = "inspection_failed"


class TWRInspectionFinding(BaseModel):
    code: str
    severity: str
    category: str
    owner_repo: str
    summary: str
    explanation: str
    recommended_action: str
    evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class TWRInspectionOwnerSummary(BaseModel):
    primary_owner_repo: str
    secondary_owner_repos: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class TWRInspectionCheckCoverage(BaseModel):
    completed_check_families: list[str] = Field(default_factory=list)
    pending_check_families: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class TWRInspectionRelatedLineage(BaseModel):
    calculation_id: UUID | None = None
    lineage_path: str | None = None

    model_config = ConfigDict(extra="forbid")


class TWRInspectionResponse(BaseModel):
    inspection_id: UUID
    subject_type: TWRInspectionSubjectType
    inspection_profile: TWRInspectionProfile
    subject_calculation_id: UUID | None = None
    portfolio_id: str | None = None
    status: str
    verdict: TWRInspectionVerdict
    findings: list[TWRInspectionFinding] = Field(default_factory=list)
    owner_summary: TWRInspectionOwnerSummary
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    check_coverage: TWRInspectionCheckCoverage
    related_lineage: TWRInspectionRelatedLineage | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    generated_at_utc: str

    model_config = ConfigDict(extra="forbid")


class TWRInspectionAcceptedResponse(BaseModel):
    inspection_id: UUID
    poll_path: str
    result_path: str

    model_config = ConfigDict(extra="forbid")
