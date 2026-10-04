"""Shared real-adapter startup proofs for SQLite and PostgreSQL."""

from contextlib import contextmanager
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect

import main
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.services import durable_metadata_bootstrap as schema_service
from app.workers import compute_executor_worker, lineage_worker, runtime_retention_worker

ENTRYPOINTS = ("api", "compute", "lineage", "retention")
WORKERS = {"compute": compute_executor_worker, "lineage": lineage_worker, "retention": runtime_retention_worker}
STORE_TYPES = {
    "execution_registry": schema_service.ExecutionRegistry,
    "compute_job_store": schema_service.ComputeJobStore,
    "async_result_store": schema_service.AsyncResultStore,
    "lineage_metadata_store": schema_service.LineageMetadataStore,
    "composite_metadata_store": schema_service.CompositeMetadataStore,
    "source_correction_store": schema_service.SourceCorrectionStore,
}


@contextmanager
def resolved_runtime_stores(database_url, monkeypatch):
    stores = {name: store_type(database_url) for name, store_type in STORE_TYPES.items()}
    for name, store in stores.items():
        # Exercise the production lazy adapters and default arguments, not a
        # replacement startup function or a verifier mocked into passing.
        monkeypatch.setattr(getattr(schema_service, name), "_resolver", lambda store=store: store)
    try:
        yield stores
    finally:
        for store in stores.values():
            store._engine.dispose()


def record_statements(stores):
    statements = []
    for store in stores.values():
        event.listen(store._engine, "before_cursor_execute", lambda _, __, sql, *args: statements.append(sql))
    return statements


def require_catalogue_only(statements):
    assert statements
    assert all(
        not sql.lstrip().upper().startswith(("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE"))
        for sql in statements
    )


def start(entrypoint):
    if entrypoint == "api":
        with TestClient(main.app) as client:
            assert client.get("/version").status_code == 200
        return
    stop = Event()
    stop.set()
    WORKERS[entrypoint].run_forever(stop_event=stop)


def assert_startup_refusal(runtime_stores, monkeypatch, entrypoint, shape):
    if shape == "missing_index":
        schema_service.bootstrap_durable_metadata_stores()
        with runtime_stores["lineage_metadata_store"]._engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX ix_lineage_payloads_created_at")
    statements = record_statements(runtime_stores)
    allocations = []
    monkeypatch.setattr(main, "configure_upstream_http_client_pool", lambda **kwargs: allocations.append(kwargs))
    if entrypoint != "api":
        action = "run_cleanup_cycle" if entrypoint == "retention" else "process_pending_jobs"
        monkeypatch.setattr(WORKERS[entrypoint], action, lambda **kwargs: pytest.fail("unverified worker polled"))
    with pytest.raises(DurableSchemaMigrationRequiredError) as error:
        start(entrypoint)
    assert error.value.code == "DURABLE_SCHEMA_MIGRATION_REQUIRED"
    if shape == "missing_index":
        assert "index:lineage_payloads.ix_lineage_payloads_created_at" in error.value.issues
    assert allocations == []
    require_catalogue_only(statements)
    if shape == "empty":
        assert inspect(runtime_stores["execution_registry"]._engine).get_table_names() == []


def assert_read_only_restart(runtime_stores, entrypoint):
    schema_service.bootstrap_durable_metadata_stores()
    statements = record_statements(runtime_stores)
    start(entrypoint)
    for store in runtime_stores.values():
        store._engine.dispose()
    start(entrypoint)
    require_catalogue_only(statements)
