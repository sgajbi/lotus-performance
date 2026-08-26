"""Concurrent worker startup must not crash a replica.

Issue #480: `MetaData.create_all` is a check-then-create, and every worker replica runs it at boot.
Two workers starting together both see a table as absent and both issue `CREATE TABLE`; the loser
dies with a `UniqueViolation` on `pg_type_typname_nsp_index` - the implicit composite type, not the
table, which is why `checkfirst` does not close it.

A real concurrent proof needs PostgreSQL and lives in the PostgreSQL concurrency contracts plus
`make lineage-volume-recovery-smoke`. These unit tests pin the things that can regress silently:
the acquisition and timeout ordering, the full store-upgrade lock boundary, and the rule that no
durable store goes back to calling `create_all` directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect

from app.services.durable_schema_creation import (
    DURABLE_SCHEMA_ADVISORY_LOCK_KEY,
    DURABLE_SCHEMA_LOCK_ACQUISITION_TIMEOUT_MS,
    create_durable_schema,
)

ROOT = Path(__file__).resolve().parents[3]
SERVICES = ROOT / "app" / "services"

# Every durable store whose schema several processes can create at once.
DURABLE_STORE_MODULES = (
    "async_result_store.py",
    "composite_metadata_store.py",
    "compute_job_store.py",
    "lineage_metadata_store.py",
    "execution_registry.py",
)


def _metadata() -> MetaData:
    metadata = MetaData()
    Table("probe_table", metadata, Column("probe_id", String(16), primary_key=True))
    return metadata


def test_sqlite_still_creates_the_schema() -> None:
    """The non-racing path must keep working, unchanged."""

    engine = create_engine("sqlite://")

    create_durable_schema(engine, _metadata())

    assert inspect(engine).has_table("probe_table")


def test_creating_twice_is_idempotent() -> None:
    """A second starter finds the tables present and does nothing."""

    engine = create_engine("sqlite://")
    metadata = _metadata()

    create_durable_schema(engine, metadata)
    create_durable_schema(engine, metadata)

    assert inspect(engine).has_table("probe_table")


def test_sqlite_does_not_attempt_an_advisory_lock() -> None:
    """`pg_advisory_xact_lock` does not exist on SQLite; calling it would break the working path."""

    engine = create_engine("sqlite://")
    statements: list[str] = []

    original_execute = engine.dialect.do_execute

    def _record(cursor, statement, parameters, context=None):  # type: ignore[no-untyped-def]
        statements.append(statement)
        return original_execute(cursor, statement, parameters, context)

    engine.dialect.do_execute = _record  # type: ignore[method-assign]
    create_durable_schema(engine, _metadata())

    assert not any("advisory" in statement.lower() for statement in statements)


def test_postgresql_bounds_advisory_acquisition_and_restores_runtime_timeouts() -> None:
    """The whole point: the lock must be taken, and taken *before* the CREATE.

    A transaction-scoped lock is required rather than a session lock - a process that dies
    mid-bootstrap must not leave the schema lock held for the next starter.
    """

    executed: list[tuple[str, object]] = []

    class _FakeResult:
        def __init__(self, value: str):
            self._value = value

        def scalar_one(self) -> str:
            return self._value

    class _FakeConnection:
        def execute(self, statement, parameters=None):  # type: ignore[no-untyped-def]
            executed.append((str(statement), parameters))
            value = "0" if "statement_timeout" in str(statement) else "5s"
            return _FakeResult(value)

        def __enter__(self) -> _FakeConnection:
            return self

        def __exit__(self, *_: object) -> None:
            executed.append(("TRANSACTION_EXIT", None))
            return None

    class _FakeDialect:
        name = "postgresql"

    class _FakeEngine:
        dialect = _FakeDialect()

        def begin(self) -> _FakeConnection:
            return _FakeConnection()

    class _RecordingMetadata:
        def create_all(self, bind: object) -> None:
            executed.append(("CREATE_ALL", None))

    def _upgrade_schema(_connection: object) -> None:
        executed.append(("UPGRADE_SCHEMA", None))

    create_durable_schema(  # type: ignore[arg-type]
        _FakeEngine(),
        _RecordingMetadata(),
        schema_upgrades=(_upgrade_schema,),
    )

    assert len(executed) == 10, executed
    assert "current_setting('lock_timeout')" in executed[0][0]
    assert "current_setting('statement_timeout')" in executed[1][0]
    assert "set_config('lock_timeout'" in executed[2][0]
    assert executed[2][1] == {"lock_timeout": "0"}
    assert "set_config('statement_timeout'" in executed[3][0]
    assert executed[3][1] == {"statement_timeout": f"{DURABLE_SCHEMA_LOCK_ACQUISITION_TIMEOUT_MS}ms"}
    assert "pg_advisory_xact_lock" in executed[4][0]
    assert "set_config('statement_timeout'" in executed[5][0]
    assert executed[5][1] == {"statement_timeout": "0"}
    assert "set_config('lock_timeout'" in executed[6][0]
    assert executed[6][1] == {"lock_timeout": "5s"}
    assert executed[7] == ("CREATE_ALL", None), "the DDL ran before the runtime timeouts were restored"
    assert executed[8] == ("UPGRADE_SCHEMA", None)
    assert executed[9] == ("TRANSACTION_EXIT", None), "the schema lock was released before store-specific DDL"


def test_the_lock_key_is_a_stable_constant() -> None:
    """Two processes only serialise if they use the same key, so it must not be derived per run."""

    assert isinstance(DURABLE_SCHEMA_ADVISORY_LOCK_KEY, int)
    assert DURABLE_SCHEMA_ADVISORY_LOCK_KEY == 0x10D55CDB
    assert DURABLE_SCHEMA_LOCK_ACQUISITION_TIMEOUT_MS > 0


@pytest.mark.parametrize("module_name", DURABLE_STORE_MODULES)
def test_no_durable_store_calls_create_all_directly(module_name: str) -> None:
    """The same defect existed in all five stores; this stops any of them regressing alone.

    An AST check rather than a text search: `Base.metadata.create_all(...)` reintroduced under a
    different alias or spelling is the same defect, and a grep for the literal would miss it.
    """

    module = SERVICES / module_name
    tree = ast.parse(module.read_text(encoding="utf-8"))

    direct_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_all"
    ]

    assert direct_calls == [], (
        f"{module_name} calls create_all directly at line(s) {direct_calls}. Concurrent worker "
        "startup then races on CREATE TABLE and crashes a replica - use create_durable_schema. "
        "See issue #480."
    )


def test_every_durable_store_uses_the_guarded_helper() -> None:
    """Every store must keep its store-specific DDL inside the guarded transaction."""

    missing_helper: list[str] = []
    missing_upgrade_boundary: list[str] = []
    for module_name in DURABLE_STORE_MODULES:
        tree = ast.parse((SERVICES / module_name).read_text(encoding="utf-8"))
        guarded_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "create_durable_schema"
        ]
        if not guarded_calls:
            missing_helper.append(module_name)
            continue
        if not any(
            keyword.arg == "schema_upgrades" and isinstance(keyword.value, ast.Tuple) and bool(keyword.value.elts)
            for call in guarded_calls
            for keyword in call.keywords
        ):
            missing_upgrade_boundary.append(module_name)

    assert missing_helper == [], f"These durable stores do not use the guarded creator: {missing_helper}"
    assert missing_upgrade_boundary == [], (
        "These durable stores release the shared startup lock before their store-specific DDL: "
        f"{missing_upgrade_boundary}"
    )
