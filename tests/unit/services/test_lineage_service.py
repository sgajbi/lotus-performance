# tests/unit/services/test_lineage_service.py
import json
import os
from uuid import uuid4

import pandas as pd
from pydantic import BaseModel

from app.services.lineage_metadata_store import LineageMetadataStore, LineageStatus
from app.services.lineage_service import LineageService


class MockModel(BaseModel):
    key: str


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

    metadata = metadata_store.get_record(calc_id)
    assert metadata is not None
    assert metadata.status == LineageStatus.COMPLETE
    assert metadata.artifact_names == ["details.csv", "request.json", "response.json"]


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
        service.materialize_payload(
            calculation_id=calc_id,
            calculation_type="TEST",
            request_json=payload.request_json,
            response_json=payload.response_json,
            calculation_details=broken_details,
        )

    assert any("Failed to capture lineage data" in record.message for record in caplog.records)
    metadata = metadata_store.get_record(calc_id)
    assert metadata is not None
    assert metadata.status == LineageStatus.FAILED


def test_lineage_service_logs_when_mark_failed_also_breaks(tmp_path, mocker, caplog):
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
    mocker.patch.object(metadata_store, "mark_failed", side_effect=RuntimeError("db down"))

    with caplog.at_level("ERROR"):
        service.materialize_payload(
            calculation_id=calc_id,
            calculation_type="TEST",
            request_json=payload.request_json,
            response_json=payload.response_json,
            calculation_details={"details.csv": None},  # type: ignore[dict-item]
        )

    assert any("Failed to mark lineage metadata record as failed" in record.message for record in caplog.records)


def test_lineage_service_create_pending_record_passthrough(tmp_path):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    service = LineageService(storage_path=str(tmp_path), metadata_store=metadata_store)
    calc_id = uuid4()

    service.create_pending_record(calculation_id=calc_id, calculation_type="TEST")

    record = metadata_store.get_record(calc_id)
    assert record is not None
    assert record.status == LineageStatus.PENDING
