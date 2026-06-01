# tests/unit/services/test_lineage_service.py
import json
import os
from uuid import uuid4

import pandas as pd
import pytest
from pydantic import BaseModel

from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR_INSPECTION
from app.services.execution_stage_names import (
    EXECUTION_STAGE_ARTIFACT_MATERIALIZATION,
    EXECUTION_STAGE_LINEAGE_MATERIALIZATION,
)
from app.services.lineage_metadata_store import LineageMetadataStore, LineageStatus
from app.services.lineage_service import LineageService, resolve_artifact_stage_name


class MockModel(BaseModel):
    key: str


def test_resolve_artifact_stage_name_uses_canonical_stage_names():
    assert (
        resolve_artifact_stage_name(calculation_type=ANALYTICS_WORKFLOW_TWR_INSPECTION)
        == EXECUTION_STAGE_ARTIFACT_MATERIALIZATION
    )
    assert resolve_artifact_stage_name(calculation_type="TWR") == EXECUTION_STAGE_LINEAGE_MATERIALIZATION


def test_lineage_service_enqueue_and_materialize(tmp_path):
    """
    Tests that the lineage service correctly creates a directory and saves
    the request, response, manifest, and CSV artifacts.
    """
    # 1. Arrange
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    service = LineageService(storage_path=str(tmp_path), metadata_store=metadata_store)
    calc_id = uuid4()
    req_model = MockModel(key="request")
    res_model = MockModel(key="response")
    details_df = pd.DataFrame([{"colA": 1, "colB": 2}])

    # 2. Act
    service.enqueue_capture(
        calculation_id=calc_id,
        calculation_type="TEST",
        request_model=req_model,
        response_model=res_model,
        calculation_details={"details.csv": details_df},
    )
    payload = metadata_store.list_pending_payloads(limit=10)[0]
    service.materialize_payload(
        calculation_id=payload.calculation_id,
        calculation_type=payload.calculation_type,
        request_json=payload.request_json,
        response_json=payload.response_json,
        calculation_details=payload.details,
    )

    # 3. Assert
    target_dir = os.path.join(tmp_path, str(calc_id))
    assert os.path.isdir(target_dir)

    # Check for all files
    req_path = os.path.join(target_dir, "request.json")
    res_path = os.path.join(target_dir, "response.json")
    csv_path = os.path.join(target_dir, "details.csv")
    manifest_path = os.path.join(target_dir, "manifest.json")

    assert os.path.exists(req_path)
    assert os.path.exists(res_path)
    assert os.path.exists(csv_path)
    assert os.path.exists(manifest_path)

    # Check manifest content
    with open(manifest_path, "r") as f:
        manifest_data = json.load(f)

    assert manifest_data["calculation_type"] == "TEST"
    assert "timestamp_utc" in manifest_data
    assert manifest_data["status"] == "complete"
    assert manifest_data["artifact_names"] == ["details.csv", "request.json", "response.json"]

    metadata = metadata_store.get_record(calc_id)
    assert metadata is not None
    assert metadata.status == LineageStatus.COMPLETE
    assert metadata.artifact_names == ["details.csv", "request.json", "response.json"]
    assert manifest_data["timestamp_utc"] == metadata.timestamp_utc
    assert manifest_data["artifact_names"] == metadata.artifact_names
    retained_payload = metadata_store.get_payload(calc_id)
    assert retained_payload is not None
    assert retained_payload.request_json == payload.request_json


def test_lineage_service_creates_storage_directory_if_missing(tmp_path):
    storage_path = tmp_path / "lineage" / "captures"
    assert not storage_path.exists()

    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    LineageService(storage_path=str(storage_path), metadata_store=metadata_store)

    assert storage_path.exists()
    assert storage_path.is_dir()


def test_lineage_service_capture_logs_error_on_write_failure(tmp_path, mocker, caplog):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    service = LineageService(storage_path=str(tmp_path), metadata_store=metadata_store)
    calc_id = uuid4()
    req_model = MockModel(key="request")
    res_model = MockModel(key="response")
    details_df = pd.DataFrame([{"colA": 1, "colB": 2}])

    service.enqueue_capture(
        calculation_id=calc_id,
        calculation_type="TEST",
        request_model=req_model,
        response_model=res_model,
        calculation_details={"details.csv": details_df},
    )
    payload = metadata_store.list_pending_payloads(limit=10)[0]
    broken_details = {**payload.details, "details.csv": None}  # type: ignore[dict-item]
    with caplog.at_level("ERROR"):
        success = service.materialize_payload(
            calculation_id=calc_id,
            calculation_type="TEST",
            request_json=payload.request_json,
            response_json=payload.response_json,
            calculation_details=broken_details,
        )

    assert success is False
    assert any("Failed to capture lineage data" in record.message for record in caplog.records)
    metadata = metadata_store.get_record(calc_id)
    assert metadata is not None
    assert metadata.status == LineageStatus.PENDING


def test_lineage_service_logs_failure_without_mutating_metadata_store(tmp_path, mocker, caplog):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    service = LineageService(storage_path=str(tmp_path), metadata_store=metadata_store)
    calc_id = uuid4()
    req_model = MockModel(key="request")
    res_model = MockModel(key="response")
    details_df = pd.DataFrame([{"colA": 1, "colB": 2}])
    service.enqueue_capture(
        calculation_id=calc_id,
        calculation_type="TEST",
        request_model=req_model,
        response_model=res_model,
        calculation_details={"details.csv": details_df},
    )
    payload = metadata_store.list_pending_payloads(limit=10)[0]
    with caplog.at_level("ERROR"):
        success = service.materialize_payload(
            calculation_id=calc_id,
            calculation_type="TEST",
            request_json=payload.request_json,
            response_json=payload.response_json,
            calculation_details={"details.csv": None},  # type: ignore[dict-item]
        )

    assert success is False
    assert any("Failed to capture lineage data" in record.message for record in caplog.records)


def test_lineage_service_create_pending_record_passthrough(tmp_path):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    service = LineageService(storage_path=str(tmp_path), metadata_store=metadata_store)
    calc_id = uuid4()

    service.create_pending_record(calculation_id=calc_id, calculation_type="TEST")

    record = metadata_store.get_record(calc_id)
    assert record is not None
    assert record.status == LineageStatus.PENDING


def test_lineage_service_uses_injected_execution_store_for_stage_completion(tmp_path, mocker):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    execution_store = mocker.Mock()
    service = LineageService(
        storage_path=str(tmp_path),
        metadata_store=metadata_store,
        execution_store=execution_store,
    )
    calc_id = uuid4()
    req_model = MockModel(key="request")
    res_model = MockModel(key="response")
    details_df = pd.DataFrame([{"colA": 1, "colB": 2}])

    service.enqueue_capture(
        calculation_id=calc_id,
        calculation_type="TEST",
        request_model=req_model,
        response_model=res_model,
        calculation_details={"details.csv": details_df},
    )
    payload = metadata_store.list_pending_payloads(limit=10)[0]

    success = service.materialize_payload(
        calculation_id=payload.calculation_id,
        calculation_type=payload.calculation_type,
        request_json=payload.request_json,
        response_json=payload.response_json,
        calculation_details=payload.details,
    )

    assert success is True
    execution_store.complete_stage.assert_called_once()


def test_lineage_service_uses_runtime_storage_path_when_not_explicit(tmp_path, mocker):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    runtime_storage_path = tmp_path / "runtime-lineage"
    mocker.patch(
        "app.services.lineage_service.get_settings",
        return_value=type("Settings", (), {"LINEAGE_STORAGE_PATH": str(runtime_storage_path)})(),
    )

    service = LineageService(metadata_store=metadata_store)

    assert service.storage_path == str(runtime_storage_path)
    assert runtime_storage_path.exists()


def test_lineage_service_rejects_unsafe_artifact_filename_on_enqueue(tmp_path):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    service = LineageService(storage_path=str(tmp_path), metadata_store=metadata_store)
    calc_id = uuid4()

    with pytest.raises(ValueError, match="Unsafe lineage artifact filename"):
        service.enqueue_capture(
            calculation_id=calc_id,
            calculation_type="TEST",
            request_model=MockModel(key="request"),
            response_model=MockModel(key="response"),
            calculation_details={"../escape.csv": pd.DataFrame([{"a": 1}])},
        )


def test_lineage_service_rejects_unsafe_artifact_filename_on_materialize(tmp_path, caplog):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    service = LineageService(storage_path=str(tmp_path), metadata_store=metadata_store)
    calc_id = uuid4()
    metadata_store.create_pending_record(calculation_id=calc_id, calculation_type="TEST")

    with caplog.at_level("ERROR"):
        success = service.materialize_payload(
            calculation_id=calc_id,
            calculation_type="TEST",
            request_json='{"key":"request"}',
            response_json='{"key":"response"}',
            calculation_details={"../escape.csv": "a\n1\n"},
        )

    assert success is False
    assert any("Unsafe lineage artifact filename" in record.message for record in caplog.records)
    record = metadata_store.get_record(calc_id)
    assert record is not None
    assert record.status == LineageStatus.PENDING


def test_lineage_service_atomic_write_does_not_leave_partial_target(tmp_path, mocker):
    target_path = tmp_path / "artifact.json"

    def _failing_replace(src, dst):
        raise OSError("replace failed")

    mocker.patch("app.services.lineage_service.os.replace", side_effect=_failing_replace)

    with pytest.raises(OSError, match="replace failed"):
        LineageService._write_text_atomic(str(target_path), '{"status":"complete"}')

    assert not target_path.exists()
    assert list(tmp_path.glob(".lineage-*.tmp")) == []


def test_lineage_service_materialize_keeps_manifest_timestamp_in_sync_with_metadata(tmp_path):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    service = LineageService(storage_path=str(tmp_path), metadata_store=metadata_store)
    calc_id = uuid4()
    req_model = MockModel(key="request")
    res_model = MockModel(key="response")
    details_df = pd.DataFrame([{"colA": 1, "colB": 2}])

    service.enqueue_capture(
        calculation_id=calc_id,
        calculation_type="TEST",
        request_model=req_model,
        response_model=res_model,
        calculation_details={"details.csv": details_df},
    )
    payload = metadata_store.list_pending_payloads(limit=10)[0]

    success = service.materialize_payload(
        calculation_id=payload.calculation_id,
        calculation_type=payload.calculation_type,
        request_json=payload.request_json,
        response_json=payload.response_json,
        calculation_details=payload.details,
    )

    assert success is True
    manifest_path = os.path.join(tmp_path, str(calc_id), "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest_data = json.load(handle)

    metadata = metadata_store.get_record(calc_id)
    assert metadata is not None
    assert metadata.timestamp_utc == manifest_data["timestamp_utc"]
    assert metadata.artifact_names == manifest_data["artifact_names"]
