from types import SimpleNamespace

import pytest

from app.services.durable_store_runtime import resolve_runtime_store
from tests.benchmarks import postgres_runtime_helpers

OWNED_URL = "postgresql+psycopg://localhost/benchmark?options=-csearch_path%3Dlotus_perf_bench_" + "a" * 32
FOREIGN_URL = "postgresql+psycopg://localhost/foreign"


class RetainedConnectionPool:
    def __init__(self):
        self.open_connections = 1

    def dispose(self):
        self.open_connections = 0


class RuntimeStore:
    def __init__(self, database_url):
        self.database_url = database_url
        self._engine = RetainedConnectionPool()


@pytest.fixture
def runtime_modules(monkeypatch):
    modules = [SimpleNamespace(_store_cache={}, resolve_runtime_store=resolve_runtime_store) for _ in range(7)]
    monkeypatch.setattr(postgres_runtime_helpers, "_runtime_store_modules", lambda: modules)
    return modules


def resolve(module, database_url=OWNED_URL):
    return module.resolve_runtime_store(cache=module._store_cache, factory=RuntimeStore, database_url=database_url)


def test_owned_runtime_scope_releases_all_startup_pools_and_preserves_foreign_entries(monkeypatch, runtime_modules):
    foreign = [resolve(module, FOREIGN_URL) for module in runtime_modules]
    with postgres_runtime_helpers.owned_postgres_runtime_stores(OWNED_URL, monkeypatch):
        owned = [resolve(module) for module in runtime_modules]
        assert all(store._engine.open_connections == 1 for store in owned)
    assert all(store._engine.open_connections == 0 for store in owned)
    for module, store in zip(runtime_modules, foreign, strict=True):
        assert module._store_cache == {FOREIGN_URL: store}
        assert store._engine.open_connections == 1
        assert module.resolve_runtime_store is resolve_runtime_store


@pytest.mark.parametrize("started", [1, 3, 6])
def test_partial_startup_exception_releases_every_allocated_pool(monkeypatch, runtime_modules, started):
    owned = []
    with pytest.raises(ValueError, match="verification refused"):
        with postgres_runtime_helpers.owned_postgres_runtime_stores(OWNED_URL, monkeypatch):
            owned = [resolve(module) for module in runtime_modules[:started]]
            raise ValueError("verification refused")
    assert len(owned) == started
    assert all(store._engine.open_connections == 0 for store in owned)
    assert all(module._store_cache == {} for module in runtime_modules)


def test_same_url_borrowed_store_is_preserved_without_disposal(monkeypatch, runtime_modules):
    borrowed = [resolve(module) for module in runtime_modules]
    with postgres_runtime_helpers.owned_postgres_runtime_stores(OWNED_URL, monkeypatch):
        assert [resolve(module) for module in runtime_modules] == borrowed
    for module, store in zip(runtime_modules, borrowed, strict=True):
        assert module._store_cache == {OWNED_URL: store}
        assert store._engine.open_connections == 1


def test_external_same_url_replacement_survives_owned_store_disposal(monkeypatch, runtime_modules):
    module = runtime_modules[0]
    replacement = RuntimeStore(OWNED_URL)
    with postgres_runtime_helpers.owned_postgres_runtime_stores(OWNED_URL, monkeypatch):
        owned = resolve(module)
        module._store_cache[OWNED_URL] = replacement
        assert resolve(module) is replacement
    assert owned._engine.open_connections == 0
    assert module._store_cache[OWNED_URL] is replacement
    assert replacement._engine.open_connections == 1


def test_close_reopen_tracks_both_real_resolver_allocations(monkeypatch, runtime_modules):
    module = runtime_modules[-1]
    with postgres_runtime_helpers.owned_postgres_runtime_stores(OWNED_URL, monkeypatch):
        original = resolve(module)
        assert module._store_cache.pop(OWNED_URL) is original
        original._engine.dispose()
        reopened = resolve(module)
        assert reopened is not original
    assert original._engine.open_connections == reopened._engine.open_connections == 0
    assert module._store_cache == {}


def test_foreign_url_created_inside_owned_scope_is_not_owned(monkeypatch, runtime_modules):
    module = runtime_modules[0]
    with postgres_runtime_helpers.owned_postgres_runtime_stores(OWNED_URL, monkeypatch):
        owned = resolve(module)
        foreign = resolve(module, FOREIGN_URL)
    assert owned._engine.open_connections == 0
    assert module._store_cache == {FOREIGN_URL: foreign}
    assert foreign._engine.open_connections == 1


@pytest.mark.parametrize("body_fails", [False, True])
def test_dispose_failure_attempts_remaining_stores_and_retains_original_failure(
    monkeypatch, runtime_modules, body_fails
):
    original = ValueError("Original test failure")
    disposal = RuntimeError("Controlled disposal failure")
    attempts = []

    def fail_disposal():
        attempts.append("failed")
        raise disposal

    with pytest.raises(BaseExceptionGroup) as error:
        with postgres_runtime_helpers.owned_postgres_runtime_stores(OWNED_URL, monkeypatch):
            owned = [resolve(module) for module in runtime_modules[:3]]
            monkeypatch.setattr(owned[-1]._engine, "dispose", fail_disposal)
            if body_fails:
                raise original
    assert error.value.exceptions == ((original, disposal) if body_fails else (disposal,))
    assert attempts == ["failed"]
    assert all(store._engine.open_connections == 0 for store in owned[:-1])
    assert owned[-1]._engine.open_connections == 1  # Attempted failure is not claimed as disposal.
    assert all(module._store_cache == {} for module in runtime_modules)
    assert all(module.resolve_runtime_store is resolve_runtime_store for module in runtime_modules)


@pytest.mark.parametrize("database_url", ["sqlite:///benchmark.db", "postgresql+psycopg://localhost/production"])
def test_runtime_ownership_refuses_nonisolated_database_before_resolver_change(
    monkeypatch, runtime_modules, database_url
):
    with pytest.raises(AssertionError):
        with postgres_runtime_helpers.owned_postgres_runtime_stores(database_url, monkeypatch):
            pytest.fail("Nonisolated URL admitted")
    assert all(module._store_cache == {} for module in runtime_modules)
    assert all(module.resolve_runtime_store is resolve_runtime_store for module in runtime_modules)


def test_get_postgres_database_url_uses_short_connect_timeout(mocker):
    engine = mocker.MagicMock()
    connection = mocker.MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    mocked_create_engine = mocker.patch(
        "tests.benchmarks.postgres_runtime_helpers.create_engine",
        return_value=engine,
    )
    mocked_uuid4 = mocker.patch("tests.benchmarks.postgres_runtime_helpers.uuid4")
    mocked_uuid4.return_value.hex = "abc123"

    database_url = postgres_runtime_helpers.get_postgres_database_url()

    assert database_url == (
        f"{postgres_runtime_helpers.POSTGRES_RUNTIME_DATABASE_URL}?options=-csearch_path%3Dlotus_perf_bench_abc123"
    )
    mocked_create_engine.assert_called_once_with(
        postgres_runtime_helpers.POSTGRES_RUNTIME_DATABASE_URL,
        future=True,
        connect_args={"connect_timeout": postgres_runtime_helpers.POSTGRES_RUNTIME_CONNECT_TIMEOUT_SECONDS},
    )
    connection.execute.assert_called_once()
    connection.exec_driver_sql.assert_called_once_with('CREATE SCHEMA IF NOT EXISTS "lotus_perf_bench_abc123"')
    engine.dispose.assert_called_once()


def test_get_postgres_database_url_appends_search_path_to_existing_options(mocker):
    engine = mocker.MagicMock()
    connection = mocker.MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    mocked_create_engine = mocker.patch(
        "tests.benchmarks.postgres_runtime_helpers.create_engine",
        return_value=engine,
    )
    mocked_uuid4 = mocker.patch("tests.benchmarks.postgres_runtime_helpers.uuid4")
    mocked_uuid4.return_value.hex = "def456"
    mocker.patch(
        "tests.benchmarks.postgres_runtime_helpers.POSTGRES_RUNTIME_DATABASE_URL",
        "postgresql+psycopg://lotus:lotus@127.0.0.1:5435/lotus_performance?options=-ctimezone%3DUTC",
    )

    database_url = postgres_runtime_helpers.get_postgres_database_url()

    assert "options=-ctimezone%3DUTC+-csearch_path%3Dlotus_perf_bench_def456" in database_url
    mocked_create_engine.assert_called_once()
    engine.dispose.assert_called_once()


def test_get_postgres_database_url_skips_when_runtime_database_is_unavailable(mocker):
    engine = mocker.MagicMock()
    engine.begin.return_value.__enter__.side_effect = postgres_runtime_helpers.OperationalError(
        "SELECT 1", {}, Exception("boom")
    )
    mocker.patch("tests.benchmarks.postgres_runtime_helpers.create_engine", return_value=engine)

    try:
        postgres_runtime_helpers.get_postgres_database_url()
    except BaseException as exc:  # pragma: no cover - pytest skip raises a framework exception
        assert exc.__class__.__name__ == "Skipped"
        assert "PostgreSQL runtime proof database unavailable" in str(exc)
    else:
        raise AssertionError("Expected get_postgres_database_url to skip when PostgreSQL is unavailable")
    engine.dispose.assert_called_once()
