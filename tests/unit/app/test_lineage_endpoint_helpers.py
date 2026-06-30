import json
from uuid import uuid4

import pytest

from app.models.lineage_responses import LineageManifest
from app.services.lineage_artifact_service import (
    downloadable_lineage_record,
    lineage_artifact_links,
    lineage_terminal_response,
    manifest_matches_record,
    read_lineage_manifest_payload,
    resolve_lineage_response,
)
from app.services.lineage_metadata_store import LineageRecord, LineageStatus
from core.errors import APIError


def test_lineage_terminal_response_projects_pending_and_failed_records():
    calculation_id = uuid4()
    pending_record = LineageRecord(
        calculation_id=calculation_id,
        calculation_type="TWR",
        status=LineageStatus.PENDING,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=[],
    )
    failed_record = LineageRecord(
        calculation_id=calculation_id,
        calculation_type="TWR",
        status=LineageStatus.FAILED,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=[],
        error_message="write failed",
    )
    complete_record = LineageRecord(
        calculation_id=calculation_id,
        calculation_type="TWR",
        status=LineageStatus.COMPLETE,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=[],
    )

    pending_response = lineage_terminal_response(calculation_id=calculation_id, record=pending_record)
    failed_response = lineage_terminal_response(calculation_id=calculation_id, record=failed_record)

    assert pending_response is not None
    assert pending_response.status == LineageStatus.PENDING
    assert pending_response.artifacts == {}
    assert pending_response.error_message is None
    assert failed_response is not None
    assert failed_response.status == LineageStatus.FAILED
    assert failed_response.error_message == "write failed"
    assert lineage_terminal_response(calculation_id=calculation_id, record=complete_record) is None


def test_resolve_lineage_response_returns_terminal_record_without_storage_lookup(mocker):
    calculation_id = uuid4()
    record = LineageRecord(
        calculation_id=calculation_id,
        calculation_type="TWR",
        status=LineageStatus.PENDING,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=[],
    )
    mocker.patch("app.services.lineage_artifact_service.lineage_metadata_store.get_record", return_value=record)
    storage_exists = mocker.patch("app.services.lineage_artifact_service.os.path.exists")

    response = resolve_lineage_response(
        calculation_id=calculation_id,
        artifact_url_factory=lambda artifact_name: f"http://testserver/artifacts/{artifact_name}",
    )

    assert response.status == LineageStatus.PENDING
    storage_exists.assert_not_called()


def test_downloadable_lineage_record_requires_complete_declared_artifact(mocker):
    calculation_id = uuid4()
    record = LineageRecord(
        calculation_id=calculation_id,
        calculation_type="TWR",
        status=LineageStatus.COMPLETE,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=["request.json"],
    )
    mocker.patch("app.services.lineage_artifact_service.lineage_metadata_store.get_record", return_value=record)

    assert downloadable_lineage_record(calculation_id=calculation_id, artifact_name="request.json") is record
    with pytest.raises(APIError, match="Lineage artifact not found"):
        downloadable_lineage_record(calculation_id=calculation_id, artifact_name="response.json")


def test_lineage_artifact_links_skip_manifest_and_build_controlled_urls():
    calculation_id = uuid4()

    links = lineage_artifact_links(
        artifact_names=["manifest.json", "request.json"],
        artifact_url_factory=lambda artifact_name: (
            f"http://testserver/lineage_artifact_file/{calculation_id}/{artifact_name}"
        ),
    )

    assert list(links) == ["request.json"]
    assert links["request.json"].url == f"http://testserver/lineage_artifact_file/{calculation_id}/request.json"


def test_read_lineage_manifest_payload_maps_storage_errors_to_unavailable(mocker):
    mocker.patch("app.services.lineage_artifact_service.read_json_file", side_effect=OSError("permission denied"))

    with pytest.raises(APIError) as exc_info:
        read_lineage_manifest_payload("manifest.json")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Lineage manifest is unreadable."


def test_read_lineage_manifest_payload_maps_invalid_json_to_unavailable(mocker):
    mocker.patch(
        "app.services.lineage_artifact_service.read_json_file",
        side_effect=json.JSONDecodeError("bad json", "", 0),
    )

    with pytest.raises(APIError) as exc_info:
        read_lineage_manifest_payload("manifest.json")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Lineage manifest is invalid."


def test_manifest_matches_record_allows_sorted_artifact_equivalence_and_rejects_mismatch():
    calculation_id = uuid4()
    record = LineageRecord(
        calculation_id=calculation_id,
        calculation_type="TWR",
        status=LineageStatus.COMPLETE,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=["response.json", "request.json"],
    )
    manifest = LineageManifest(
        calculation_type="TWR",
        timestamp_utc="2026-01-01T00:00:00Z",
        status="complete",
        artifact_names=["request.json", "response.json"],
    )

    assert manifest_matches_record(manifest=manifest, record=record)

    mismatched_manifest = manifest.model_copy(update={"artifact_names": ["request.json"]})
    assert not manifest_matches_record(manifest=mismatched_manifest, record=record)
