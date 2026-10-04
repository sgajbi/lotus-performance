import os
import re
import sys
from contextlib import contextmanager
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

POSTGRES_RUNTIME_DATABASE_URL = os.getenv(
    "LOTUS_POSTGRES_PLAN_DATABASE_URL",
    "postgresql+psycopg://lotus:lotus@127.0.0.1:5435/lotus_performance",
)
POSTGRES_RUNTIME_CONNECT_TIMEOUT_SECONDS = 3

RUNTIME_STORE_MODULES = (
    "app.services.execution_registry",
    "app.services.compute_job_store",
    "app.services.async_result_store",
    "app.services.lineage_metadata_store",
    "app.services.composite_metadata_store",
    "app.services.source_correction_store",
    "app.adapters.composite_materialization_repository",
)


def _runtime_store_modules():
    return [import_module(name) for name in RUNTIME_STORE_MODULES]


def _require_isolated_postgres_url(database_url):
    url = make_url(database_url)
    options = url.query.get("options", "")
    assert url.get_backend_name() == "postgresql"
    assert isinstance(options, str)
    assert re.search(
        r"(?:^|\s)-csearch_path=lotus_perf_bench_[0-9a-f]{32}(?:\s|$)", options
    ), "Runtime-store ownership requires the benchmark helper's isolated schema URL"


@contextmanager
def owned_postgres_runtime_stores(database_url, monkeypatch):
    """Observe genuine resolver allocations without replacing caches or store factories."""
    _require_isolated_postgres_url(database_url)
    modules = _runtime_store_modules()
    borrowed = {id(store) for module in modules for store in module._store_cache.values()}
    owned = []
    with monkeypatch.context() as ownership:
        for module in modules:
            ownership.setattr(
                module,
                "resolve_runtime_store",
                _observe_runtime_resolver(module.resolve_runtime_store, database_url, borrowed, owned),
            )
        try:
            yield
        finally:
            original = sys.exception()
            failures = _dispose_owned_runtime_stores(database_url, owned)
            if failures:
                errors = ([original] if original is not None else []) + failures
                raise BaseExceptionGroup("Owned PostgreSQL runtime cleanup failed", errors)


def _dispose_owned_runtime_stores(database_url, owned):
    failures = []
    for cache, store in reversed(owned):
        try:
            if cache.get(database_url) is store:
                cache.pop(database_url)
            store._engine.dispose()
        except Exception as error:
            failures.append(error)
    return failures


def _observe_runtime_resolver(resolver, owned_database_url, borrowed, owned):
    def observe(*, cache, factory, database_url=None):
        def allocate(active_database_url):
            store = factory(active_database_url)
            if active_database_url == owned_database_url and id(store) not in borrowed:
                owned.append((cache, store))
            return store

        return resolver(cache=cache, factory=allocate, database_url=database_url)

    return observe


def get_postgres_database_url() -> str:
    isolated_schema_name = f"lotus_perf_bench_{uuid4().hex}"
    engine = create_engine(
        POSTGRES_RUNTIME_DATABASE_URL,
        future=True,
        connect_args={"connect_timeout": POSTGRES_RUNTIME_CONNECT_TIMEOUT_SECONDS},
    )
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT 1"))
            connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{isolated_schema_name}"')
    except OperationalError:
        pytest.skip(f"PostgreSQL runtime proof database unavailable at {POSTGRES_RUNTIME_DATABASE_URL}")
    finally:
        engine.dispose()
    database_url = make_url(POSTGRES_RUNTIME_DATABASE_URL)
    existing_options = database_url.query.get("options")
    search_path_option = f"-csearch_path={isolated_schema_name}"
    combined_options = f"{existing_options} {search_path_option}".strip() if existing_options else search_path_option
    return database_url.update_query_dict({"options": combined_options}).render_as_string(hide_password=False)
