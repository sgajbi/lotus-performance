from __future__ import annotations

from app.models.lineage_responses import LineageArtifactMetadata

_RAW_PAYLOAD_ARTIFACTS = {"request.json", "response.json"}
_CUSTOMER_CONSUMABLE_ARTIFACTS = {"support_brief.md"}


def lineage_artifact_metadata(*, artifact_name: str) -> LineageArtifactMetadata:
    if artifact_name in _CUSTOMER_CONSUMABLE_ARTIFACTS:
        return LineageArtifactMetadata(
            access_classification="customer_consumable",
            intended_audience="customer",
            sensitivity="customer_safe_summary",
            minimization_posture="customer_safe_transformed",
            retention_category="lineage_support_pack",
            redaction_required_before_external_sharing=False,
        )
    if artifact_name in _RAW_PAYLOAD_ARTIFACTS:
        return LineageArtifactMetadata(
            access_classification="operator_only",
            intended_audience="operations",
            sensitivity="raw_sensitive_payload",
            minimization_posture="raw_payload_full_fidelity",
            retention_category="lineage_raw_payload",
            redaction_required_before_external_sharing=True,
        )
    return LineageArtifactMetadata(
        access_classification="operator_only",
        intended_audience="operations",
        sensitivity="derived_evidence",
        minimization_posture="derived_detail_minimized",
        retention_category="lineage_detail_evidence",
        redaction_required_before_external_sharing=True,
    )


def lineage_artifact_metadata_by_name(*, artifact_names: list[str]) -> dict[str, LineageArtifactMetadata]:
    return {artifact_name: lineage_artifact_metadata(artifact_name=artifact_name) for artifact_name in artifact_names}
