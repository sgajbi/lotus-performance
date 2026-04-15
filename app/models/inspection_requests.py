from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.twr_requests import TWRAnalyticsRequest

TWR_INSPECTION_REQUEST_EXAMPLES = [
    {
        "inspection_id": "9d000001-1111-4222-8333-abcdefabcdef",
        "subject_type": "twr_calculation",
        "subject_calculation_id": "6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91",
        "inspection_profile": "support_triage",
    },
    {
        "inspection_id": "9d000002-1111-4222-8333-abcdefabcdef",
        "subject_type": "twr_request",
        "inspection_profile": "canonical_validation",
        "request": {
            "input_mode": "stateless",
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "performance_start_date": "2026-01-01",
            "metric_basis": "NET",
            "report_end_date": "2026-04-10",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "stateless_input": {
                "valuation_points": [
                    {
                        "perf_date": "2026-04-10",
                        "begin_mv": 1000000.0,
                        "bod_cf": 0.0,
                        "eod_cf": 0.0,
                        "mgmt_fees": -125.0,
                        "end_mv": 1000141.0,
                    }
                ]
            },
        },
    },
]


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
        examples=["9d000001-1111-4222-8333-abcdefabcdef"],
    )
    subject_type: TWRInspectionSubjectType = Field(description="Inspection subject mode.")
    subject_calculation_id: UUID | None = Field(
        default=None,
        description="Existing TWR calculation to inspect when subject_type is twr_calculation.",
        examples=["6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91"],
    )
    request: TWRAnalyticsRequest | None = Field(
        default=None,
        description=(
            "Fresh TWR request to inspect when subject_type is twr_request. This does not replace "
            "the normal TWR calculation endpoint; it runs supportability checks against the supplied "
            "request shape."
        ),
    )
    inspection_profile: TWRInspectionProfile = Field(
        default=TWRInspectionProfile.SUPPORT_TRIAGE,
        description=(
            "Bounded inspection behavior profile. Use support_triage for normal support work, "
            "canonical_validation for governed portfolio validation, and deep_reconciliation for "
            "heavier upstream reconciliation evidence."
        ),
        examples=["support_triage"],
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": TWR_INSPECTION_REQUEST_EXAMPLES},
    )

    @model_validator(mode="after")
    def validate_subject_mode(self) -> "TWRInspectionRequest":
        if self.subject_type == TWRInspectionSubjectType.TWR_CALCULATION:
            if self.subject_calculation_id is None or self.request is not None:
                raise ValueError(
                    "twr_calculation inspection requires subject_calculation_id and does not accept request payload."
                )
        elif self.subject_calculation_id is not None or self.request is None:
            raise ValueError(
                "twr_request inspection requires request payload and does not accept subject_calculation_id."
            )
        return self
