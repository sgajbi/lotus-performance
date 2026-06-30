from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.endpoints.inspections import (
    _inspection_portfolio_id,
    _inspection_requested_window,
    _inspection_storage_path,
    _is_available_twr_inspection_artifact,
    _is_completed_twr_inspection_record,
    _retained_inspection_artifact_response,
    _safe_inspection_artifact_name,
)
from app.models.inspection_requests import TWRInspectionRequest
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR_INSPECTION
from app.services.lineage_metadata_store import LineagePayload, LineageRecord, LineageStatus


def test_is_completed_twr_inspection_record_requires_complete_twr_record():
    inspection_id = uuid4()
    complete_record = LineageRecord(
        calculation_id=inspection_id,
        calculation_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
        status=LineageStatus.COMPLETE,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=["inspection_summary.json"],
    )
    pending_record = LineageRecord(
        calculation_id=inspection_id,
        calculation_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
        status=LineageStatus.PENDING,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=["inspection_summary.json"],
    )

    assert _is_completed_twr_inspection_record(complete_record) is True
    assert _is_completed_twr_inspection_record(pending_record) is False
    assert _is_completed_twr_inspection_record(None) is False


def test_is_available_twr_inspection_artifact_requires_complete_record_and_artifact_name():
    inspection_id = uuid4()
    complete_record = LineageRecord(
        calculation_id=inspection_id,
        calculation_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
        status=LineageStatus.COMPLETE,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=["inspection_summary.json"],
    )
    pending_record = LineageRecord(
        calculation_id=inspection_id,
        calculation_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
        status=LineageStatus.PENDING,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=["inspection_summary.json"],
    )

    assert _is_available_twr_inspection_artifact(complete_record, "inspection_summary.json") is True
    assert _is_available_twr_inspection_artifact(complete_record, "support_brief.md") is False
    assert _is_available_twr_inspection_artifact(pending_record, "inspection_summary.json") is False
    assert _is_available_twr_inspection_artifact(None, "inspection_summary.json") is False


@pytest.mark.parametrize(
    "artifact_name",
    [
        "",
        " ",
        ".",
        "..",
        "../outside.json",
        r"..\outside.json",
        "/tmp/outside.json",
        r"C:\tmp\outside.json",
        "nested/file.json",
        r"nested\file.json",
        "bad\nname.json",
    ],
)
def test_safe_inspection_artifact_name_rejects_path_like_values(artifact_name):
    assert _safe_inspection_artifact_name(artifact_name) is None


def test_safe_inspection_artifact_name_accepts_single_file_name():
    assert _safe_inspection_artifact_name(" support_brief.md ") == "support_brief.md"


def test_inspection_storage_path_rejects_unsafe_artifact_names():
    inspection_id = uuid4()

    with pytest.raises(ValueError, match="Unsafe TWR inspection artifact filename"):
        _inspection_storage_path(inspection_id=inspection_id, artifact_name=r"..\outside.json")


def test_is_available_twr_inspection_artifact_ignores_unsafe_metadata_names():
    inspection_id = uuid4()
    complete_record = LineageRecord(
        calculation_id=inspection_id,
        calculation_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
        status=LineageStatus.COMPLETE,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=[r"..\outside.json", "inspection_summary.json"],
    )

    assert _is_available_twr_inspection_artifact(complete_record, r"..\outside.json") is False
    assert _is_available_twr_inspection_artifact(complete_record, "inspection_summary.json") is True


def test_retained_inspection_artifact_response_sets_markdown_media_type_and_attachment():
    artifact_name = "support_brief.md"
    payload = LineagePayload(
        calculation_id=uuid4(),
        calculation_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
        request_json="{}",
        response_json="{}",
        details={artifact_name: "# Support"},
        attempt_count=0,
    )

    response = _retained_inspection_artifact_response(payload=payload, artifact_name=artifact_name)

    assert response is not None
    assert response.media_type == "text/markdown"
    assert response.headers["content-disposition"] == f'attachment; filename="{artifact_name}"'
    assert response.body == b"# Support"
    assert _retained_inspection_artifact_response(payload=payload, artifact_name="missing.json") is None


def test_retained_inspection_artifact_response_rejects_unsafe_content_disposition_filename():
    artifact_name = r"..\outside.json"
    payload = LineagePayload(
        calculation_id=uuid4(),
        calculation_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
        request_json="{}",
        response_json="{}",
        details={artifact_name: '{"unsafe":true}'},
        attempt_count=0,
    )

    assert _retained_inspection_artifact_response(payload=payload, artifact_name=artifact_name) is None


def test_inspection_submission_helpers_project_request_subject_metadata(mocker):
    subject_calculation_id = uuid4()
    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(subject_calculation_id),
            "inspection_profile": "deep_reconciliation",
        }
    )
    mocker.patch(
        "app.api.endpoints.inspections.execution_registry.get_execution",
        return_value=SimpleNamespace(portfolio_id="PORTFOLIO_001"),
    )

    assert _inspection_portfolio_id(request) == "PORTFOLIO_001"
    assert _inspection_requested_window(request) == {
        "subject_type": "twr_calculation",
        "inspection_profile": "deep_reconciliation",
        "subject_calculation_id": str(subject_calculation_id),
    }
