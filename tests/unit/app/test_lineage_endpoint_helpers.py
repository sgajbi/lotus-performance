from uuid import uuid4

from starlette.datastructures import URL

from app.api.endpoints.lineage import _lineage_artifact_links, _lineage_terminal_response, _manifest_matches_record
from app.models.lineage_responses import LineageManifest
from app.services.lineage_metadata_store import LineageRecord, LineageStatus


class _RequestStub:
    def url_for(self, name: str, **path_params: str) -> URL:
        return URL(f"http://testserver/{name}/{path_params['calculation_id']}/{path_params['artifact_name']}")


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

    pending_response = _lineage_terminal_response(calculation_id=calculation_id, record=pending_record)
    failed_response = _lineage_terminal_response(calculation_id=calculation_id, record=failed_record)

    assert pending_response is not None
    assert pending_response.status == LineageStatus.PENDING
    assert pending_response.artifacts == {}
    assert pending_response.error_message is None
    assert failed_response is not None
    assert failed_response.status == LineageStatus.FAILED
    assert failed_response.error_message == "write failed"
    assert _lineage_terminal_response(calculation_id=calculation_id, record=complete_record) is None


def test_lineage_artifact_links_skip_manifest_and_build_controlled_urls():
    calculation_id = uuid4()

    links = _lineage_artifact_links(
        request=_RequestStub(),
        calculation_id=calculation_id,
        artifact_names=["manifest.json", "request.json"],
    )

    assert list(links) == ["request.json"]
    assert links["request.json"].url == f"http://testserver/lineage_artifact_file/{calculation_id}/request.json"


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

    assert _manifest_matches_record(manifest=manifest, record=record)

    mismatched_manifest = manifest.model_copy(update={"artifact_names": ["request.json"]})
    assert not _manifest_matches_record(manifest=mismatched_manifest, record=record)
