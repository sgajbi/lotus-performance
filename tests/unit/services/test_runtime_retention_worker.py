from threading import Event

import pytest

from app.workers import runtime_retention_worker


def _worker_settings(**overrides):
    return type(
        "Settings",
        (),
        {
            "LOG_LEVEL": "INFO",
            "RUNTIME_RETENTION_WORKER_POLL_SECONDS": 60.0,
            "RUNTIME_RETENTION_WORKER_APPLY": False,
            "RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID": "runtime-retention-automation",
            "RUNTIME_RETENTION_AUTOMATION_JOB_ID": "retention-nightly",
            **overrides,
        },
    )()


def test_runtime_retention_worker_run_cleanup_cycle_uses_scheduled_identity(monkeypatch):
    settings = _worker_settings(RUNTIME_RETENTION_WORKER_APPLY=True)
    captured: dict[str, object] = {}

    def _execute_runtime_retention_cleanup(**kwargs):
        captured.update(kwargs)
        return type(
            "Evidence",
            (),
            {
                "cleanup_mode": "apply",
                "status": "applied",
                "prunable_execution_count": 1,
            },
        )()

    monkeypatch.setattr(
        runtime_retention_worker, "execute_runtime_retention_cleanup", _execute_runtime_retention_cleanup
    )

    runtime_retention_worker.run_cleanup_cycle(settings=settings)

    assert captured == {
        "apply": True,
        "operator_id": "runtime-retention-automation",
        "trigger_mode": "scheduled",
        "job_id": "retention-nightly",
    }


def test_runtime_retention_worker_run_forever_bootstraps_and_sleeps(monkeypatch):
    calls: list[str] = []
    settings = _worker_settings(RUNTIME_RETENTION_WORKER_POLL_SECONDS=15.0)

    monkeypatch.setattr(
        runtime_retention_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema")
    )
    monkeypatch.setattr(
        runtime_retention_worker.compute_job_store, "create_schema", lambda: calls.append("compute_schema")
    )
    monkeypatch.setattr(
        runtime_retention_worker.async_result_store, "create_schema", lambda: calls.append("result_schema")
    )
    monkeypatch.setattr(
        runtime_retention_worker.lineage_metadata_store, "create_schema", lambda: calls.append("lineage_schema")
    )
    monkeypatch.setattr(
        runtime_retention_worker,
        "run_cleanup_cycle",
        lambda **kwargs: (
            calls.append("cleanup")
            or type("Evidence", (), {"cleanup_mode": "dry_run", "status": "planned", "prunable_execution_count": 0})()
        ),
    )

    def _sleep(seconds: float):
        calls.append(f"sleep:{seconds}")
        raise RuntimeError("stop loop")

    monkeypatch.setattr(runtime_retention_worker.time, "sleep", _sleep)

    with pytest.raises(RuntimeError, match="stop loop"):
        runtime_retention_worker.run_forever(settings=settings)

    assert calls == [
        "exec_schema",
        "compute_schema",
        "result_schema",
        "lineage_schema",
        "cleanup",
        "sleep:15.0",
    ]


def test_runtime_retention_worker_run_forever_honors_pre_set_stop_event(monkeypatch):
    stop_event = Event()
    stop_event.set()
    calls: list[str] = []

    monkeypatch.setattr(
        runtime_retention_worker.execution_registry, "create_schema", lambda: calls.append("exec_schema")
    )
    monkeypatch.setattr(
        runtime_retention_worker.compute_job_store, "create_schema", lambda: calls.append("compute_schema")
    )
    monkeypatch.setattr(
        runtime_retention_worker.async_result_store, "create_schema", lambda: calls.append("result_schema")
    )
    monkeypatch.setattr(
        runtime_retention_worker.lineage_metadata_store, "create_schema", lambda: calls.append("lineage_schema")
    )
    monkeypatch.setattr(runtime_retention_worker, "run_cleanup_cycle", lambda **kwargs: calls.append("cleanup"))

    runtime_retention_worker.run_forever(stop_event=stop_event, settings=_worker_settings())

    assert calls == ["exec_schema", "compute_schema", "result_schema", "lineage_schema"]


def test_runtime_retention_worker_stop_helpers_cover_none_and_event_paths():
    stop_event = Event()
    assert runtime_retention_worker._stop_requested(None) is False
    assert runtime_retention_worker._stop_requested(stop_event) is False
    stop_event.set()
    assert runtime_retention_worker._stop_requested(stop_event) is True


def test_runtime_retention_worker_wait_for_next_poll_honors_event(monkeypatch):
    stop_event = Event()
    stop_event.set()

    assert runtime_retention_worker._wait_for_next_poll(stop_event, 5.0) is True
