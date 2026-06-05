from threading import Event
from uuid import uuid4

import pandas as pd
import pytest
from pydantic import BaseModel

from app.services.lineage_metadata_store import LineageMetadataStore, LineagePayload, LineageStatus
from app.services.lineage_service import LineageService
from app.workers import lineage_worker


def _worker_settings(**overrides):
    return type(
        "Settings",
        (),
        {
            "LOG_LEVEL": "INFO",
            "LINEAGE_WORKER_BATCH_SIZE": 10,
            "LINEAGE_WORKER_ID": "lineage-worker-test",
            "LINEAGE_WORKER_LEASE_SECONDS": 30,
            "LINEAGE_WORKER_MAX_ATTEMPTS": 3,
            "LINEAGE_WORKER_POLL_SECONDS": 5.0,
            **overrides,
        },
    )()


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


def test_process_pending_jobs_retries_failed_materialization_until_budget_exhausted(monkeypatch, tmp_path):
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
    monkeypatch.setattr(service, "materialize_payload", lambda **kwargs: False)
    settings = _worker_settings(LINEAGE_WORKER_MAX_ATTEMPTS=2)

    first_processed = lineage_worker.process_pending_jobs(limit=10, settings=settings)
    first_record = metadata_store.get_record(calculation_id)
    first_payload = metadata_store.get_payload(calculation_id)

    second_processed = lineage_worker.process_pending_jobs(limit=10, settings=settings)
    second_record = metadata_store.get_record(calculation_id)
    second_payload = metadata_store.get_payload(calculation_id)

    assert first_processed == 0
    assert first_record is not None
    assert first_record.status == LineageStatus.PENDING
    assert first_payload is not None
    assert first_payload.attempt_count == 1

    assert second_processed == 0
    assert second_record is not None
    assert second_record.status == LineageStatus.FAILED
    assert second_record.error_message == "Lineage materialization failed after exhausting retry budget."
    assert second_payload is not None
    assert second_payload.attempt_count == 2


def test_materialize_leased_payload_ignores_stale_missing_payload():
    calculation_id = uuid4()
    payload = LineagePayload(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_json='{"key":"request"}',
        response_json='{"key":"response"}',
        details={},
        attempt_count=1,
    )
    calls: list[str] = []

    class _LineageService:
        def materialize_payload(self, **kwargs):
            calls.append(f"materialize:{kwargs['calculation_id']}")
            return False

    class _LineageStore:
        def delete_payload(self, calculation_id):
            calls.append(f"delete:{calculation_id}")

        def get_payload(self, calculation_id):
            calls.append(f"get:{calculation_id}")
            return None

        def mark_pending(self, calculation_id):
            calls.append(f"pending:{calculation_id}")

        def mark_failed(self, *, calculation_id, error_message):
            calls.append(f"failed:{calculation_id}:{error_message}")

    class _ExecutionStore:
        def fail_stage(self, *args):
            calls.append("fail_stage")

    processed = lineage_worker._materialize_leased_payload(
        payload=payload,
        lineage_store=_LineageStore(),
        lineage_service_=_LineageService(),
        execution_store=_ExecutionStore(),
        max_attempts=2,
    )

    assert processed is False
    assert calls == [
        f"materialize:{calculation_id}",
        f"get:{calculation_id}",
    ]


def test_run_forever_initializes_schema_and_sleeps_when_idle(monkeypatch):
    calls: list[str] = []
    settings = _worker_settings(LINEAGE_WORKER_POLL_SECONDS=11.0)

    def _create_schema():
        calls.append("schema")

    def _process_pending_jobs(**kwargs):
        calls.append("process")
        return 0

    def _sleep(seconds: float):
        calls.append(f"sleep:{seconds}")
        raise RuntimeError("stop loop")

    monkeypatch.setattr(lineage_worker.lineage_metadata_store, "create_schema", _create_schema)
    monkeypatch.setattr(lineage_worker, "process_pending_jobs", _process_pending_jobs)
    monkeypatch.setattr(lineage_worker.time, "sleep", _sleep)

    with pytest.raises(RuntimeError, match="stop loop"):
        lineage_worker.run_forever(settings=settings)

    assert calls == ["schema", "process", f"sleep:{settings.LINEAGE_WORKER_POLL_SECONDS}"]


def test_lineage_worker_run_forever_honors_pre_set_stop_event(monkeypatch):
    stop_event = Event()
    stop_event.set()
    calls: list[str] = []
    settings = _worker_settings()

    monkeypatch.setattr(lineage_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema"))
    monkeypatch.setattr(lineage_worker.lineage_metadata_store, "create_schema", lambda: calls.append("lineage_schema"))
    monkeypatch.setattr(lineage_worker, "process_pending_jobs", lambda **kwargs: calls.append("process") or 1)

    lineage_worker.run_forever(stop_event=stop_event, settings=settings)

    assert calls == ["exec_schema", "lineage_schema"]


def test_lineage_worker_run_forever_stops_during_idle_wait(monkeypatch):
    stop_event = Event()
    calls: list[str] = []
    settings = _worker_settings(LINEAGE_WORKER_POLL_SECONDS=4.0)

    monkeypatch.setattr(lineage_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema"))
    monkeypatch.setattr(lineage_worker.lineage_metadata_store, "create_schema", lambda: calls.append("lineage_schema"))
    monkeypatch.setattr(lineage_worker, "process_pending_jobs", lambda **kwargs: calls.append("process") or 0)

    def _wait(timeout: float) -> bool:
        calls.append(f"wait:{timeout}")
        stop_event.set()
        return True

    monkeypatch.setattr(stop_event, "wait", _wait)

    lineage_worker.run_forever(stop_event=stop_event, settings=settings)

    assert calls == [
        "exec_schema",
        "lineage_schema",
        "process",
        f"wait:{settings.LINEAGE_WORKER_POLL_SECONDS}",
    ]
