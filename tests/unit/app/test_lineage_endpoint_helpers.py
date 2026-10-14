import json
from uuid import uuid4

import pytest

from app.models.lineage_responses import LineageManifest
from app.services.lineage_artifact_classification import lineage_artifact_metadata_by_name
from app.services.lineage_artifact_service import (
    downloadable_lineage_record,
    lineage_artifact_links,
    lineage_terminal_response,
    load_and_validate_manifest,
    manifest_matches_record,
    read_lineage_manifest_payload,
    resolve_lineage_response,
)
from app.services.lineage_metadata_store import LineageRecord, LineageStatus
from core.errors import APIError


@pytest.mark.parametrize("downgrade", [False, True])
def test_inventory_projection_checks_operator_floor_before_minting_urls(downgrade):
    names = ["source-raw.bin", "request.json", "support_brief.md"]
    metadata = lineage_artifact_metadata_by_name(artifact_names=names)
    if downgrade:
        metadata["source-raw.bin"] = metadata["support_brief.md"]
    minted = []

    def url(name):
        minted.append(name)
        return f"https://example.test/{name}"

    links = lineage_artifact_links(
        artifact_names=names, artifact_metadata=metadata, artifact_url_factory=url, include_operator_artifacts=False
    )
    assert set(links) == {"support_brief.md"} and minted == ["support_brief.md"]
    operator_links = lineage_artifact_links(artifact_names=names, artifact_metadata=metadata, artifact_url_factory=url)
    assert operator_links["source-raw.bin"].access_classification == "operator_only"
    assert operator_links["source-raw.bin"].redaction_required_before_external_sharing is True


@pytest.mark.parametrize("name", ["source-raw.bin", "request.json", "daily_results.csv"])
def test_inventory_enforces_every_canonical_metadata_field(name):
    canonical = lineage_artifact_metadata_by_name(artifact_names=[name])[name]
    unsafe = lineage_artifact_metadata_by_name(artifact_names=["support_brief.md"])["support_brief.md"]
    unsafe = unsafe.model_copy(update={"access_classification": "operator_only"})
    links = lineage_artifact_links(
        artifact_names=[name], artifact_metadata={name: unsafe}, artifact_url_factory=lambda filename: filename
    )
    assert links[name].model_dump(exclude={"url"}) == canonical.model_dump()


def test_inventory_preserves_manifest_policy_stricter_than_derived_filename():
    strict = lineage_artifact_metadata_by_name(artifact_names=["request.json"])["request.json"]
    links = lineage_artifact_links(
        artifact_names=["daily_results.csv"],
        artifact_metadata={"daily_results.csv": strict},
        artifact_url_factory=lambda filename: filename,
    )
    assert links["daily_results.csv"].model_dump(exclude={"url"}) == strict.model_dump()


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
        artifact_metadata=lineage_artifact_metadata_by_name(artifact_names=["request.json"]),
        artifact_url_factory=lambda artifact_name: (
            f"http://testserver/lineage_artifact_file/{calculation_id}/{artifact_name}"
        ),
    )

    assert list(links) == ["request.json"]
    assert links["request.json"].url == f"http://testserver/lineage_artifact_file/{calculation_id}/request.json"
    assert links["request.json"].access_classification == "operator_only"
    assert links["request.json"].sensitivity == "raw_sensitive_payload"


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
        artifacts=lineage_artifact_metadata_by_name(artifact_names=["request.json", "response.json"]),
    )

    assert manifest_matches_record(manifest=manifest, record=record)

    mismatched_manifest = manifest.model_copy(update={"artifact_names": ["request.json"]})
    assert not manifest_matches_record(manifest=mismatched_manifest, record=record)


def test_load_and_validate_manifest_classifies_legacy_artifact_names(tmp_path):
    calculation_id = uuid4()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "calculation_type": "TWR",
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "status": "complete",
                "artifact_names": ["request.json", "daily_results.csv"],
            }
        ),
        encoding="utf-8",
    )
    record = LineageRecord(
        calculation_id=calculation_id,
        calculation_type="TWR",
        status=LineageStatus.COMPLETE,
        timestamp_utc="2026-01-01T00:00:00Z",
        artifact_names=["daily_results.csv", "request.json"],
    )

    manifest = load_and_validate_manifest(manifest_path=str(manifest_path), record=record)

    assert manifest.artifacts["request.json"].sensitivity == "raw_sensitive_payload"
    assert manifest.artifacts["daily_results.csv"].sensitivity == "derived_evidence"
