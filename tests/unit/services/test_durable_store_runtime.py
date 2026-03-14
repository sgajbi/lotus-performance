from __future__ import annotations

from pathlib import Path

from app.services import (
    async_result_store,
    compute_job_store,
    durable_store_runtime,
    execution_registry,
    lineage_metadata_store,
)


class _Settings:
    def __init__(self, database_url: str):
        self.LINEAGE_METADATA_DATABASE_URL = database_url


def _sqlite_url(tmp_path: Path, name: str) -> str:
    return f"sqlite:///{tmp_path / name}"


def test_compute_job_store_resolves_runtime_database_url(monkeypatch, tmp_path):
    first_url = _sqlite_url(tmp_path, "compute-first.db")
    second_url = _sqlite_url(tmp_path, "compute-second.db")
    monkeypatch.setattr(durable_store_runtime, "get_settings", lambda: _Settings(first_url))

    first_store = compute_job_store.get_compute_job_store()
    same_store = compute_job_store.get_compute_job_store()

    monkeypatch.setattr(durable_store_runtime, "get_settings", lambda: _Settings(second_url))

    second_store = compute_job_store.get_compute_job_store()

    assert first_store is same_store
    assert second_store is not first_store
    assert compute_job_store.compute_job_store._engine is second_store._engine


def test_execution_registry_proxy_resolves_runtime_database_url(monkeypatch, tmp_path):
    first_url = _sqlite_url(tmp_path, "execution-first.db")
    second_url = _sqlite_url(tmp_path, "execution-second.db")
    monkeypatch.setattr(durable_store_runtime, "get_settings", lambda: _Settings(first_url))

    first_registry = execution_registry.get_execution_registry()
    first_registry.create_schema()
    assert "analytics_execution" in first_registry.list_table_names()

    monkeypatch.setattr(durable_store_runtime, "get_settings", lambda: _Settings(second_url))

    second_registry = execution_registry.get_execution_registry()
    second_registry.create_schema()

    assert second_registry is not first_registry
    assert execution_registry.execution_registry.list_table_names()
    assert "analytics_execution" in execution_registry.execution_registry.list_table_names()


def test_lineage_metadata_store_proxy_resolves_runtime_database_url(monkeypatch, tmp_path):
    first_url = _sqlite_url(tmp_path, "lineage-first.db")
    second_url = _sqlite_url(tmp_path, "lineage-second.db")
    monkeypatch.setattr(durable_store_runtime, "get_settings", lambda: _Settings(first_url))

    first_store = lineage_metadata_store.get_lineage_metadata_store()
    monkeypatch.setattr(durable_store_runtime, "get_settings", lambda: _Settings(second_url))
    second_store = lineage_metadata_store.get_lineage_metadata_store()

    assert second_store is not first_store
    assert lineage_metadata_store.lineage_metadata_store._engine is second_store._engine


def test_async_result_store_proxy_resolves_runtime_database_url(monkeypatch, tmp_path):
    first_url = _sqlite_url(tmp_path, "result-first.db")
    second_url = _sqlite_url(tmp_path, "result-second.db")
    monkeypatch.setattr(durable_store_runtime, "get_settings", lambda: _Settings(first_url))

    first_store = async_result_store.get_async_result_store()
    monkeypatch.setattr(durable_store_runtime, "get_settings", lambda: _Settings(second_url))
    second_store = async_result_store.get_async_result_store()

    assert second_store is not first_store
    assert async_result_store.async_result_store._engine is second_store._engine
