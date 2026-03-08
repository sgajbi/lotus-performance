from uuid import uuid4

import pandas as pd
import pytest
from pydantic import BaseModel

from app.services.lineage_metadata_store import LineageMetadataStore, LineageStatus
from app.services.lineage_service import LineageService
from app.workers import lineage_worker


class _Model(BaseModel):
    key: str


def test_process_pending_jobs_materializes_payload(monkeypatch, tmp_path):
    metadata_store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata_store.create_schema()
    service = LineageService(storage_path=str(tmp_path), metadata_store=metadata_store)
    calculation_id = uuid4()

    service.enqueue_capture(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_model=_Model(key="request"),
        response_model=_Model(key="response"),
        calculation_details={"details.csv": pd.DataFrame([{"a": 1}])},
    )

    monkeypatch.setattr(lineage_worker, "lineage_metadata_store", metadata_store)
    monkeypatch.setattr(lineage_worker, "lineage_service", service)

    processed = lineage_worker.process_pending_jobs(limit=10)

    assert processed == 1
    assert (tmp_path / str(calculation_id) / "details.csv").exists()
    record = metadata_store.get_record(calculation_id)
    assert record is not None
    assert record.status == LineageStatus.COMPLETE
    assert metadata_store.list_pending_payloads(limit=10) == []


def test_run_forever_initializes_schema_and_sleeps_when_idle(monkeypatch):
    calls: list[str] = []

    def _create_schema():
        calls.append("schema")

    def _process_pending_jobs():
        calls.append("process")
        return 0

    def _sleep(seconds: float):
        calls.append(f"sleep:{seconds}")
        raise RuntimeError("stop loop")

    monkeypatch.setattr(lineage_worker.lineage_metadata_store, "create_schema", _create_schema)
    monkeypatch.setattr(lineage_worker, "process_pending_jobs", _process_pending_jobs)
    monkeypatch.setattr(lineage_worker.time, "sleep", _sleep)

    with pytest.raises(RuntimeError, match="stop loop"):
        lineage_worker.run_forever()

    assert calls == ["schema", "process", f"sleep:{lineage_worker.settings.LINEAGE_WORKER_POLL_SECONDS}"]
