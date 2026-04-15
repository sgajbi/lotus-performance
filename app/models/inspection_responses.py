from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.inspection_requests import TWRInspectionProfile, TWRInspectionSubjectType

TWR_INSPECTION_FINDING_EXAMPLE = {
    "code": "EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH",
    "severity": "high",
    "category": "cashflow_classification",
    "owner_repo": "lotus-performance",
    "summary": "External cash-flow economics do not tie to served TWR valuation points.",
    "explanation": "The inspector compared raw upstream cash-flow rows to normalized bod/eod cash flows.",
    "recommended_action": "Review the source-economics artifact and fix the normalization path or upstream payload.",
    "evidence": {
        "valuation_date": "2026-03-12",
        "expected_bod_cashflow": "5000.0",
        "normalized_bod_cf": "0.0",
    },
}

TWR_INSPECTION_RESPONSE_EXAMPLES = [
    {
        "inspection_id": "9d000001-1111-4222-8333-abcdefabcdef",
        "subject_type": "twr_calculation",
        "inspection_profile": "support_triage",
        "subject_calculation_id": "6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "status": "complete",
        "verdict": "supportable_with_warnings",
        "findings": [TWR_INSPECTION_FINDING_EXAMPLE],
        "owner_summary": {
            "primary_owner_repo": "lotus-performance",
            "secondary_owner_repos": ["lotus-core"],
        },
        "evidence_summary": {
            "completed_check_families": 5,
            "nonpositive_capital_base_count": 0,
            "reconciliation_gap_date_count": 0,
        },
        "check_coverage": {
            "completed_check_families": [
                "calculation_consistency",
                "source_quality",
                "economic_plausibility",
                "reconciliation",
                "cashflow_classification",
            ],
            "pending_check_families": [],
        },
        "related_lineage": {
            "calculation_id": "6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91",
            "lineage_path": "/performance/lineage/6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91",
        },
        "artifacts": {
            "inspection_summary.json": (
                "/performance/inspections/9d000001-1111-4222-8333-abcdefabcdef/artifacts/inspection_summary.json"
            ),
            "findings.json": ("/performance/inspections/9d000001-1111-4222-8333-abcdefabcdef/artifacts/findings.json"),
            "source_economics_summary.json": (
                "/performance/inspections/9d000001-1111-4222-8333-abcdefabcdef/artifacts/source_economics_summary.json"
            ),
        },
        "generated_at_utc": "2026-04-10T10:30:00Z",
    }
]

TWR_INSPECTION_ACCEPTED_RESPONSE_EXAMPLES = [
    {
        "inspection_id": "9d000001-1111-4222-8333-abcdefabcdef",
        "poll_path": "/performance/executions/9d000001-1111-4222-8333-abcdefabcdef",
        "result_path": "/performance/inspections/9d000001-1111-4222-8333-abcdefabcdef",
    }
]


class TWRInspectionVerdict(StrEnum):
    SUPPORTABLE = "supportable"
    SUPPORTABLE_WITH_WARNINGS = "supportable_with_warnings"
    NOT_SUPPORTABLE = "not_supportable"
    INSPECTION_FAILED = "inspection_failed"


class TWRInspectionFinding(BaseModel):
    code: str = Field(
        description="Stable machine-readable finding code from the TWR inspector inventory.",
        examples=["EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH"],
    )
    severity: str = Field(
        description="Supportability severity: info, warning, high, or critical.",
        examples=["high"],
    )
    category: str = Field(
        description="Finding family such as source_quality, reconciliation, or cashflow_classification.",
        examples=["cashflow_classification"],
    )
    owner_repo: str = Field(
        description="Lotus repository that most likely owns the defect or follow-up action.",
        examples=["lotus-performance"],
    )
    summary: str = Field(
        description="Short support-facing summary of the detected issue.",
        examples=["External cash-flow economics do not tie to served TWR valuation points."],
    )
    explanation: str = Field(
        description="Detailed explanation of why the finding was raised and how evidence was interpreted.",
        examples=["The inspector compared raw upstream cash-flow rows to normalized bod/eod cash flows."],
    )
    recommended_action: str = Field(
        description="Concrete support or engineering action recommended by the inspector.",
        examples=["Review the source-economics artifact and fix the normalization path or upstream payload."],
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured finding-specific evidence. Shape varies by finding code.",
        examples=[TWR_INSPECTION_FINDING_EXAMPLE["evidence"]],
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [TWR_INSPECTION_FINDING_EXAMPLE]},
    )


class TWRInspectionOwnerSummary(BaseModel):
    primary_owner_repo: str = Field(
        description="Repository with the highest weighted ownership score across findings.",
        examples=["lotus-performance"],
    )
    secondary_owner_repos: list[str] = Field(
        default_factory=list,
        description="Other repositories represented by the inspection findings, ordered by weighted severity.",
        examples=[["lotus-core"]],
    )

    model_config = ConfigDict(extra="forbid")


class TWRInspectionCheckCoverage(BaseModel):
    completed_check_families: list[str] = Field(
        default_factory=list,
        description="Inspector check families that completed and contributed evidence to the verdict.",
        examples=[
            [
                "calculation_consistency",
                "source_quality",
                "economic_plausibility",
                "reconciliation",
                "cashflow_classification",
            ]
        ],
    )
    pending_check_families: list[str] = Field(
        default_factory=list,
        description="Inspector check families that did not run for this subject or remain unavailable.",
        examples=[[]],
    )

    model_config = ConfigDict(extra="forbid")


class TWRInspectionRelatedLineage(BaseModel):
    calculation_id: UUID | None = Field(
        default=None,
        description="TWR calculation identifier inspected when subject_type is twr_calculation.",
        examples=["6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91"],
    )
    lineage_path: str | None = Field(
        default=None,
        description="Service-local lineage route for the inspected TWR calculation when available.",
        examples=["/performance/lineage/6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91"],
    )

    model_config = ConfigDict(extra="forbid")


class TWRInspectionResponse(BaseModel):
    inspection_id: UUID = Field(
        description="Durable inspection identifier used for execution polling, result retrieval, and artifacts.",
        examples=["9d000001-1111-4222-8333-abcdefabcdef"],
    )
    subject_type: TWRInspectionSubjectType = Field(description="Inspection subject mode that was executed.")
    inspection_profile: TWRInspectionProfile = Field(description="Bounded inspection behavior profile that was run.")
    subject_calculation_id: UUID | None = Field(
        default=None,
        description="Inspected TWR calculation identifier when the subject is an existing calculation.",
        examples=["6af3a15f-8b95-4b4f-9c4c-6bb9f4d86a91"],
    )
    portfolio_id: str | None = Field(
        default=None,
        description="Portfolio identifier resolved from the inspected request or calculation lineage.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    status: str = Field(description="Terminal inspection result status.", examples=["complete"])
    verdict: TWRInspectionVerdict = Field(
        description="Supportability verdict synthesized from completed, failed, and pending check families."
    )
    findings: list[TWRInspectionFinding] = Field(
        default_factory=list,
        description="Ordered supportability findings with owner, severity, recommended action, and evidence.",
        examples=[[TWR_INSPECTION_FINDING_EXAMPLE]],
    )
    owner_summary: TWRInspectionOwnerSummary = Field(
        description="Repository ownership summary synthesized from finding owners and severities."
    )
    evidence_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Flat count and summary metrics emitted by completed inspector check families.",
        examples=[{"nonpositive_capital_base_count": 0, "reconciliation_gap_date_count": 0}],
    )
    check_coverage: TWRInspectionCheckCoverage = Field(
        description="Check-family coverage showing which supportability checks contributed to the verdict."
    )
    related_lineage: TWRInspectionRelatedLineage | None = Field(
        default=None,
        description="Lineage pointer for the inspected TWR calculation when available.",
    )
    artifacts: dict[str, str] = Field(
        default_factory=dict,
        description="Artifact name to download-path map for inspection evidence files.",
        examples=[
            {
                "inspection_summary.json": (
                    "/performance/inspections/9d000001-1111-4222-8333-abcdefabcdef/artifacts/inspection_summary.json"
                ),
                "findings.json": (
                    "/performance/inspections/9d000001-1111-4222-8333-abcdefabcdef/artifacts/findings.json"
                ),
            }
        ],
    )
    generated_at_utc: str = Field(
        description="UTC timestamp when the inspection response was generated.",
        examples=["2026-04-10T10:30:00Z"],
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": TWR_INSPECTION_RESPONSE_EXAMPLES},
    )


class TWRInspectionAcceptedResponse(BaseModel):
    inspection_id: UUID = Field(
        description="Durable inspection identifier accepted for async execution.",
        examples=["9d000001-1111-4222-8333-abcdefabcdef"],
    )
    poll_path: str = Field(
        description="Execution polling route for queue, running, stage, and terminal status.",
        examples=["/performance/executions/9d000001-1111-4222-8333-abcdefabcdef"],
    )
    result_path: str = Field(
        description="Endpoint-specific route that returns the completed TWR inspection result.",
        examples=["/performance/inspections/9d000001-1111-4222-8333-abcdefabcdef"],
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": TWR_INSPECTION_ACCEPTED_RESPONSE_EXAMPLES},
    )
