from threading import Event
from uuid import uuid4

import pandas as pd
import pytest
from pydantic import BaseModel

from app.services.lineage_metadata_store import (
    LineageMetadataStore,
    LineagePayload,
    LineagePayloadLeaseOwnershipError,
    LineageStatus,
)
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
        def delete_payload(self, calculation_id, *, worker_id=None):
            assert worker_id is None
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


def test_materialize_leased_payload_skips_stale_owner_without_retry(monkeypatch):
    calculation_id = uuid4()
    payload = LineagePayload(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_json='{"key":"request"}',
        response_json='{"key":"response"}',
        details={},
        attempt_count=2,
        worker_id="lineage-worker-a",
    )
    calls: list[str] = []
    warnings: list[tuple[tuple, dict]] = []

    class _LineageService:
        def materialize_payload(self, **kwargs):
            calls.append(f"materialize:{kwargs['calculation_id']}:{kwargs['worker_id']}")
            raise LineagePayloadLeaseOwnershipError("lease owner mismatch")

    class _LineageStore:
        def delete_payload(self, *args, **kwargs):
            raise AssertionError("stale owner must not delete active payload")

        def get_payload(self, calculation_id):
            calls.append(f"get:{calculation_id}")
            raise AssertionError("stale owner must not enter retry handling")

        def mark_pending(self, calculation_id):
            raise AssertionError("stale owner must not clear replacement lease")

        def mark_failed(self, *, calculation_id, error_message):
            raise AssertionError("stale owner must not mark lineage failed")

    monkeypatch.setattr(
        lineage_worker.logger,
        "warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    processed = lineage_worker._materialize_leased_payload(
        payload=payload,
        lineage_store=_LineageStore(),
        lineage_service_=_LineageService(),
        execution_store=object(),
        max_attempts=3,
    )

    assert processed is False
    assert calls == [f"materialize:{calculation_id}:lineage-worker-a"]
    assert warnings and warnings[0][0] == (
        "Skipped lineage payload finalization because worker no longer owns the active lease.",
    )
    extra_fields = warnings[0][1]["extra"]["extra_fields"]
    assert extra_fields["failure_classification"] == "stale_owner_lineage_finalization_skipped"


def test_lineage_worker_runtime_prefers_explicit_overrides():
    class _LineageStore:
        pass

    class _LineageService:
        pass

    class _ExecutionStore:
        pass

    lineage_store = _LineageStore()
    lineage_service = _LineageService()
    execution_store = _ExecutionStore()

    runtime = lineage_worker._lineage_worker_runtime(
        limit=7,
        lineage_store=lineage_store,
        lineage_service_=lineage_service,
        execution_store=execution_store,
        worker_id="worker-explicit",
        lease_seconds=45,
        max_attempts=5,
        settings=_worker_settings(
            LINEAGE_WORKER_BATCH_SIZE=10,
            LINEAGE_WORKER_ID="worker-settings",
            LINEAGE_WORKER_LEASE_SECONDS=30,
            LINEAGE_WORKER_MAX_ATTEMPTS=3,
        ),
    )

    assert runtime.batch_size == 7
    assert runtime.lineage_store is lineage_store
    assert runtime.lineage_service is lineage_service
    assert runtime.execution_store is execution_store
    assert runtime.worker_id == "worker-explicit"
    assert runtime.lease_seconds == 45
    assert runtime.max_attempts == 5


def test_lineage_worker_runtime_uses_settings_for_omitted_values(monkeypatch):
    class _LineageStore:
        pass

    class _LineageService:
        pass

    class _ExecutionStore:
        pass

    lineage_store = _LineageStore()
    lineage_service = _LineageService()
    execution_store = _ExecutionStore()
    monkeypatch.setattr(lineage_worker, "lineage_metadata_store", lineage_store)
    monkeypatch.setattr(lineage_worker, "lineage_service", lineage_service)
    monkeypatch.setattr(lineage_worker, "execution_registry", execution_store)

    runtime = lineage_worker._lineage_worker_runtime(
        limit=None,
        lineage_store=None,
        lineage_service_=None,
        execution_store=None,
        worker_id=None,
        lease_seconds=None,
        max_attempts=None,
        settings=_worker_settings(
            LINEAGE_WORKER_BATCH_SIZE=11,
            LINEAGE_WORKER_ID="worker-settings",
            LINEAGE_WORKER_LEASE_SECONDS=31,
            LINEAGE_WORKER_MAX_ATTEMPTS=4,
        ),
    )

    assert runtime.batch_size == 11
    assert runtime.lineage_store is lineage_store
    assert runtime.lineage_service is lineage_service
    assert runtime.execution_store is execution_store
    assert runtime.worker_id == "worker-settings"
    assert runtime.lease_seconds == 31
    assert runtime.max_attempts == 4


def test_lineage_worker_explicit_or_default_preserves_falsy_fallback_behavior():
    assert lineage_worker._explicit_or_default(None, "fallback") == "fallback"
    assert lineage_worker._explicit_or_default("", "fallback") == "fallback"
    assert lineage_worker._explicit_or_default(0, 7) == 7
    assert lineage_worker._explicit_or_default("explicit", "fallback") == "explicit"


def test_mark_lineage_materialization_failed_logs_structured_stage_fields(monkeypatch):
    calculation_id = uuid4()
    warnings: list[tuple[tuple, dict]] = []
    calls: list[str] = []

    class _LineageStore:
        def mark_failed(self, *, calculation_id, error_message):
            calls.append(f"mark_failed:{calculation_id}:{error_message}")

    class _ExecutionStore:
        def fail_stage(self, *args):
            raise KeyError("missing stage")

    monkeypatch.setattr(lineage_worker.logger, "warning", lambda *args, **kwargs: warnings.append((args, kwargs)))

    lineage_worker._mark_lineage_materialization_failed(
        calculation_id=calculation_id,
        calculation_type="TWR",
        lineage_store=_LineageStore(),
        execution_store=_ExecutionStore(),
        error_message="Lineage materialization failed after exhausting retry budget.",
    )

    assert calls == [
        f"mark_failed:{calculation_id}:Lineage materialization failed after exhausting retry budget.",
    ]
    assert [warning[0][0] for warning in warnings] == [
        "Lineage materialization failed after retry budget",
        "Execution stage unavailable while marking lineage materialization failed",
    ]
    terminal_fields = warnings[0][1]["extra"]["extra_fields"]
    assert terminal_fields["worker_name"] == "lineage_worker"
    assert terminal_fields["queue"] == "lineage"
    assert terminal_fields["calculation_id"] == str(calculation_id)
    assert terminal_fields["calculation_type"] == "TWR"
    assert terminal_fields["lineage_stage"] == "lineage_materialization"
    assert terminal_fields["failure_classification"] == "terminal_lineage_materialization_failure"
    assert terminal_fields["retryable"] is False
    stage_fields = warnings[1][1]["extra"]["extra_fields"]
    assert stage_fields["failure_classification"] == "lineage_execution_stage_unavailable"
    assert stage_fields["lineage_stage"] == "lineage_materialization"


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
