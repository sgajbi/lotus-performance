from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.twr_requests import TWRAnalyticsRequest


class TWRInspectionSubjectType(StrEnum):
    TWR_CALCULATION = "twr_calculation"
    TWR_REQUEST = "twr_request"


class TWRInspectionProfile(StrEnum):
    SUPPORT_TRIAGE = "support_triage"
    CANONICAL_VALIDATION = "canonical_validation"
    DEEP_RECONCILIATION = "deep_reconciliation"


class TWRInspectionRequest(BaseModel):
    inspection_id: UUID = Field(
        default_factory=uuid4,
        description="Client-supplied or service-generated durable inspection identifier.",
    )
    subject_type: TWRInspectionSubjectType = Field(description="Inspection subject mode.")
    subject_calculation_id: UUID | None = Field(
        default=None,
        description="Existing TWR calculation to inspect when subject_type is twr_calculation.",
    )
    request: TWRAnalyticsRequest | None = Field(
        default=None,
        description="Fresh TWR request to inspect when subject_type is twr_request.",
    )
    inspection_profile: TWRInspectionProfile = Field(
        default=TWRInspectionProfile.SUPPORT_TRIAGE,
        description="Bounded inspection behavior profile.",
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_subject_mode(self) -> "TWRInspectionRequest":
        if self.subject_type == TWRInspectionSubjectType.TWR_CALCULATION:
            if self.subject_calculation_id is None or self.request is not None:
                raise ValueError(
                    "twr_calculation inspection requires subject_calculation_id and does not accept request payload."
                )
        elif self.subject_calculation_id is not None or self.request is None:
            raise ValueError("twr_request inspection requires request payload and does not accept subject_calculation_id.")
        return self
