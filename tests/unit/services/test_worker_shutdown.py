import runpy
import signal
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace

import pytest

from app.services import durable_metadata_bootstrap
from app.workers import compute_executor_worker, lineage_worker, shutdown

WORKERS = (compute_executor_worker, lineage_worker)
SIGNALS = (signal.SIGTERM, signal.SIGINT)


@pytest.fixture(params=WORKERS, ids=("compute", "lineage"))
def worker(request, monkeypatch):
    module = request.param
    settings = SimpleNamespace(
        LOG_LEVEL="INFO",
        COMPUTE_EXECUTOR_WORKER_ID="shutdown-test",
        LINEAGE_WORKER_ID="shutdown-test",
        COMPUTE_EXECUTOR_POLL_SECONDS=600.0,
        LINEAGE_WORKER_POLL_SECONDS=600.0,
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "setup_worker_logging", lambda level: None)
    monkeypatch.setattr(module, "verify_durable_metadata_stores", lambda **kwargs: None)
    return module


@pytest.mark.parametrize("signum", SIGNALS)
def test_entrypoint_signal_wakes_idle_poll_and_restores_handlers(worker, monkeypatch, signum):
    original_handlers = {item: signal.getsignal(item) for item in SIGNALS}
    calls = []
    original_wait = Event.wait

    def idle_batch(**kwargs):
        calls.append("claim")
        return 0

    def signal_during_wait(event, timeout):
        assert timeout == 600.0
        assert not event.is_set()
        signal.raise_signal(signum)
        assert original_wait(event, timeout=0) is True
        calls.append("awakened")
        return True

    monkeypatch.setattr(worker, "process_pending_jobs", idle_batch)
    monkeypatch.setattr(Event, "wait", signal_during_wait)

    worker.main()

    assert calls == ["claim", "awakened"]
    assert {item: signal.getsignal(item) for item in SIGNALS} == original_handlers


@pytest.mark.parametrize("signum", SIGNALS)
def test_signal_finishes_actual_admitted_batch_without_next_claim(worker, monkeypatch, signum):
    calls = []
    admitted = [object(), object()]

    def lease_batch(**kwargs):
        calls.append("claim")
        return admitted

    def finish_admitted(item, *args, **kwargs):
        calls.append(item)
        if item is admitted[0]:
            signal.raise_signal(signum)
        return True

    if worker is compute_executor_worker:
        runtime = SimpleNamespace(
            job_store=SimpleNamespace(lease_pending_jobs=lease_batch),
            worker_id="shutdown-test",
            batch_size=2,
            lease_seconds=30,
        )
        monkeypatch.setattr(worker, "_build_compute_job_runtime", lambda **kwargs: runtime)
        monkeypatch.setattr(worker, "_reconcile_stale_compute_jobs", lambda runtime: None)
        monkeypatch.setattr(worker, "_process_leased_compute_job", finish_admitted)
    else:
        runtime = SimpleNamespace(
            lineage_store=SimpleNamespace(lease_pending_payloads=lease_batch),
            lineage_service=object(),
            execution_store=object(),
            worker_id="shutdown-test",
            batch_size=2,
            lease_seconds=30,
            max_attempts=3,
        )
        monkeypatch.setattr(worker, "_lineage_worker_runtime", lambda **kwargs: runtime)
        monkeypatch.setattr(worker, "_reconcile_stranded_source_custody", lambda runtime: None)
        monkeypatch.setattr(
            worker, "_materialize_leased_payload", lambda *, payload, **kwargs: finish_admitted(payload)
        )

    worker.main()

    assert calls == ["claim", *admitted]


def test_entrypoint_preserves_error_and_restores_handlers_after_signal(worker, monkeypatch):
    original_handlers = {item: signal.getsignal(item) for item in SIGNALS}
    failure = RuntimeError("admitted batch failure")

    def failed_batch(**kwargs):
        signal.raise_signal(signal.SIGTERM)
        raise failure

    monkeypatch.setattr(worker, "process_pending_jobs", failed_batch)

    with pytest.raises(RuntimeError) as caught:
        worker.main()

    assert caught.value is failure
    assert {item: signal.getsignal(item) for item in SIGNALS} == original_handlers


@pytest.mark.parametrize("module", WORKERS, ids=("compute", "lineage"))
def test_python_module_entrypoint_installs_signal_bridge(module, monkeypatch):
    calls = []
    original_shutdown_signals = shutdown.shutdown_signals

    @contextmanager
    def stopped_at_startup():
        with original_shutdown_signals() as stop_event:
            signal.raise_signal(signal.SIGTERM)
            assert stop_event.is_set()
            calls.append("signal_bridge")
            yield stop_event

    monkeypatch.setattr(shutdown, "shutdown_signals", stopped_at_startup)
    monkeypatch.setattr(
        durable_metadata_bootstrap, "verify_durable_metadata_stores", lambda **kwargs: calls.append("verify")
    )
    # A pre-set event exercises the real -m dispatch without queue or database access.
    with pytest.warns(RuntimeWarning, match="found in sys.modules"):
        runpy.run_module(module.__name__, run_name="__main__")

    assert calls == ["signal_bridge", "verify"]


def test_partial_signal_installation_restores_previous_handler(monkeypatch):
    original_signal = shutdown.signal
    previous = signal.getsignal(signal.SIGTERM)
    failure = RuntimeError("interrupt handler unavailable")

    def fail_interrupt_installation(signum, handler):
        if signum == signal.SIGINT:
            raise failure
        return original_signal(signum, handler)

    monkeypatch.setattr(shutdown, "signal", fail_interrupt_installation)

    with pytest.raises(RuntimeError) as caught, shutdown.shutdown_signals():
        pytest.fail("worker must not start with partial signal installation")

    assert caught.value is failure
    assert signal.getsignal(signal.SIGTERM) == previous
