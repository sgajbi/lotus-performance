from __future__ import annotations

import json
from uuid import UUID

from app.models.inspection_requests import TWRInspectionRequest
from app.models.inspection_responses import TWRInspectionResponse
from app.services.lineage_metadata_store import lineage_metadata_store

INSPECTION_ARTIFACT_FILENAMES = (
    "inspection_summary.json",
    "findings.json",
    "support_brief.md",
)


def enqueue_twr_inspection_artifacts(
    *,
    inspection_id: UUID,
    request_model: TWRInspectionRequest,
    response_model: TWRInspectionResponse,
    artifact_payloads: dict[str, str] | None = None,
) -> None:
    details = {
        "inspection_summary.json": response_model.model_dump_json(indent=2),
        "findings.json": json.dumps(
            [finding.model_dump(mode="json") for finding in response_model.findings],
            indent=2,
        ),
    }
    if artifact_payloads:
        details.update(artifact_payloads)
    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=inspection_id,
        calculation_type="TWR_INSPECTION",
        request_json=request_model.model_dump_json(indent=2),
        response_json=response_model.model_dump_json(indent=2),
        details=details,
    )
