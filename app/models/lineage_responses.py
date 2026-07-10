from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.services.lineage_metadata_store import LineageStatus

LineageAccessClassification = Literal["operator_only", "customer_consumable"]
LineageIntendedAudience = Literal["operations", "customer"]
LineageSensitivity = Literal["raw_sensitive_payload", "derived_evidence", "customer_safe_summary"]
LineageMinimizationPosture = Literal[
    "raw_payload_full_fidelity",
    "derived_detail_minimized",
    "customer_safe_transformed",
]
LineageRetentionCategory = Literal["lineage_raw_payload", "lineage_detail_evidence", "lineage_support_pack"]


class LineageArtifactMetadata(BaseModel):
    access_classification: LineageAccessClassification = Field(
        description="Governed artifact access class; raw lineage files are operator-only by default.",
        examples=["operator_only"],
    )
    intended_audience: LineageIntendedAudience = Field(
        description="Audience allowed to consume this exact artifact without a separate transformation.",
        examples=["operations"],
    )
    sensitivity: LineageSensitivity = Field(
        description="Sensitivity and data-minimization posture for the materialized artifact payload.",
        examples=["raw_sensitive_payload"],
    )
    minimization_posture: LineageMinimizationPosture = Field(
        description="Whether the artifact is raw, minimized derived evidence, or explicitly customer-safe.",
        examples=["raw_payload_full_fidelity"],
    )
    retention_category: LineageRetentionCategory = Field(
        description="Retention category used by operators when applying lineage retention policy.",
        examples=["lineage_raw_payload"],
    )
    redaction_required_before_external_sharing: bool = Field(
        description="Whether this exact artifact requires redaction or transformation before customer sharing.",
        examples=[True],
    )


class ArtifactLink(LineageArtifactMetadata):
    url: str = Field(
        description="Controlled service-owned download URL for this lineage artifact.",
        examples=[
            "http://performance.dev.lotus/performance/lineage/2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e/artifacts/request.json"
        ],
    )


class LineageResponse(BaseModel):
    calculation_id: UUID = Field(
        description="Durable calculation identifier whose lineage is being inspected.",
        examples=["2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"],
    )
    calculation_type: str = Field(
        description="Analytics family that produced the lineage payload.",
        examples=["TWR"],
    )
    timestamp_utc: str = Field(
        description="UTC timestamp from the durable lineage record or completed manifest.",
        examples=["2026-04-10T12:00:00Z"],
    )
    status: LineageStatus = Field(
        description="Durable lineage materialization status.",
        examples=["complete"],
    )
    artifacts: dict[str, ArtifactLink] = Field(
        description=(
            "Download links keyed by artifact filename. Empty while lineage is pending or failed, "
            "and populated only after manifest and on-disk artifact integrity checks pass."
        ),
        examples=[
            {
                "request.json": {
                    "url": (
                        "http://performance.dev.lotus/performance/lineage/"
                        "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e/artifacts/request.json"
                    ),
                    "access_classification": "operator_only",
                    "intended_audience": "operations",
                    "sensitivity": "raw_sensitive_payload",
                    "minimization_posture": "raw_payload_full_fidelity",
                    "retention_category": "lineage_raw_payload",
                    "redaction_required_before_external_sharing": True,
                }
            }
        ],
    )
    error_message: str | None = Field(
        default=None,
        description="Lineage materialization failure message when status is failed.",
        examples=["write failed"],
    )


class LineageManifest(BaseModel):
    calculation_type: str = Field(description="Analytics family recorded in manifest.", examples=["TWR"])
    timestamp_utc: str = Field(
        description="UTC completion timestamp recorded in manifest.", examples=["2026-04-10T12:00:00Z"]
    )
    status: str = Field(description="Manifest materialization status.", examples=["complete"])
    artifact_names: list[str] = Field(
        description="Sorted artifact filenames declared by the manifest.",
        examples=[["daily_results.csv", "request.json", "response.json"]],
    )
    artifacts: dict[str, LineageArtifactMetadata] = Field(
        description="Per-artifact classification, audience, minimization, and retention metadata.",
        examples=[
            {
                "request.json": {
                    "access_classification": "operator_only",
                    "intended_audience": "operations",
                    "sensitivity": "raw_sensitive_payload",
                    "minimization_posture": "raw_payload_full_fidelity",
                    "retention_category": "lineage_raw_payload",
                    "redaction_required_before_external_sharing": True,
                }
            }
        ],
    )

    @model_validator(mode="after")
    def artifact_metadata_matches_declared_names(self) -> LineageManifest:
        declared = set(self.artifact_names)
        metadata_names = set(self.artifacts)
        if declared != metadata_names:
            raise ValueError("Lineage manifest artifact metadata must match artifact_names.")
        return self
