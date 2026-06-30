from uuid import uuid4

import pytest

from app.api.endpoints import inspections as inspections_endpoint
from app.api.endpoints.inspections import (
    _retained_inspection_artifact_response,
)
from app.models.inspection_requests import TWRInspectionRequest
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR_INSPECTION
from app.services.inspection.twr_inspection_artifact_service import (
    RetainedTWRInspectionArtifact,
    inspection_storage_path,
    is_available_twr_inspection_artifact,
    is_completed_twr_inspection_record,
    retained_inspection_artifact,
    safe_inspection_artifact_name,
)
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

    assert is_completed_twr_inspection_record(complete_record) is True
    assert is_completed_twr_inspection_record(pending_record) is False
    assert is_completed_twr_inspection_record(None) is False


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

    assert is_available_twr_inspection_artifact(complete_record, "inspection_summary.json") is True
    assert is_available_twr_inspection_artifact(complete_record, "support_brief.md") is False
    assert is_available_twr_inspection_artifact(pending_record, "inspection_summary.json") is False
    assert is_available_twr_inspection_artifact(None, "inspection_summary.json") is False


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
    assert safe_inspection_artifact_name(artifact_name) is None


def test_safe_inspection_artifact_name_accepts_single_file_name():
    assert safe_inspection_artifact_name(" support_brief.md ") == "support_brief.md"


def test_inspection_storage_path_rejects_unsafe_artifact_names():
    inspection_id = uuid4()

    with pytest.raises(ValueError, match="Unsafe TWR inspection artifact filename"):
        inspection_storage_path(inspection_id=inspection_id, artifact_name=r"..\outside.json")


def test_is_available_twr_inspection_artifact_ignores_unsafe_metadata_names():
    inspection_id = uuid4()
    complete_record = LineageRecord(
        calculation_id=inspection_id,
        calculation_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
        status=LineageStatus.COMPLETE,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=[r"..\outside.json", "inspection_summary.json"],
    )

    assert is_available_twr_inspection_artifact(complete_record, r"..\outside.json") is False
    assert is_available_twr_inspection_artifact(complete_record, "inspection_summary.json") is True


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

    artifact = retained_inspection_artifact(payload=payload, artifact_name=artifact_name)
    assert artifact is not None
    response = _retained_inspection_artifact_response(artifact)

    assert response is not None
    assert response.media_type == "text/markdown"
    assert response.headers["content-disposition"] == f'attachment; filename="{artifact_name}"'
    assert response.body == b"# Support"
    assert retained_inspection_artifact(payload=payload, artifact_name="missing.json") is None


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

    assert retained_inspection_artifact(payload=payload, artifact_name=artifact_name) is None


def test_retained_inspection_artifact_response_sets_content_disposition_from_reference():
    response = _retained_inspection_artifact_response(
        RetainedTWRInspectionArtifact(
            content="# Support",
            media_type="text/markdown",
            filename="support_brief.md",
        )
    )

    assert response.media_type == "text/markdown"
    assert response.headers["content-disposition"] == 'attachment; filename="support_brief.md"'
    assert response.body == b"# Support"


def test_submit_twr_inspection_endpoint_delegates_to_workflow(mocker):
    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_request",
            "inspection_profile": "support_triage",
            "request": {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "performance_start_date": "2026-01-01",
                "metric_basis": "NET",
                "report_end_date": "2026-01-02",
                "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                "valuation_points": [{"perf_date": "2026-01-02", "begin_mv": 1000.0, "end_mv": 1001.0}],
            },
        }
    )
    expected_response = object()
    workflow = mocker.patch(
        "app.api.endpoints.inspections.submit_twr_inspection_workflow",
        return_value=expected_response,
    )

    response = inspections_endpoint.submit_twr_inspection(request)

    workflow.assert_called_once_with(request)
    assert response is expected_response
