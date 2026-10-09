"""Original response custody is independent of ordinary async retention."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.services.async_result_store import AsyncResultCaptureAdmissionRequiredError, AsyncResultModel, AsyncResultStore

CAPTURE_TYPE = "COMPOSITE_TWR_CANDIDATE"


@pytest.fixture
def captured_result(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'captured.db'}"
    store = AsyncResultStore(database_url)
    store.create_schema()
    calculation_id = uuid4()
    now = datetime.now(UTC) - timedelta(days=90)
    with store._session() as session:
        session.add(
            AsyncResultModel(
                calculation_id=str(calculation_id),
                tenant_id="tenant-a",
                analytics_type=CAPTURE_TYPE,
                result_status="complete",
                response_json=json.dumps(
                    {"calculation_id": str(calculation_id), "cumulative_return": "0.030200000000"}
                ),
                created_at_utc=now,
                updated_at_utc=now,
            )
        )
    yield store, calculation_id, database_url
    store._engine.dispose()


def _snapshot(store):
    with store._engine.connect() as connection:
        return tuple(connection.execute(select(AsyncResultModel.__table__)).all())


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE analytics_async_result SET response_json = '{}'",
        "UPDATE analytics_async_result SET analytics_type = 'TWR'",
        "UPDATE analytics_async_result SET tenant_id = 'tenant-b'",
        "UPDATE analytics_async_result SET updated_at_utc = CURRENT_TIMESTAMP",
        "DELETE FROM analytics_async_result",
    ],
)
def test_captured_original_refuses_mutation(captured_result, mutation):
    store, _, _ = captured_result
    before = _snapshot(store)
    with pytest.raises(IntegrityError, match="immutable"):
        with store._engine.begin() as connection:
            connection.execute(text(mutation))
    assert _snapshot(store) == before


def test_capture_retention_excludes_original_and_keeps_ordinary_retention(captured_result):
    store, calculation_id, _ = captured_result
    before = _snapshot(store)
    ordinary = uuid4()
    store.record_success(
        calculation_id=ordinary, analytics_type="TWR", tenant_id="tenant-a", response_payload={"value": "0.2"}
    )
    cutoff = datetime.now(UTC) + timedelta(days=1)
    assert store.list_result_ids_older_than(cutoff) == [str(ordinary)]
    assert store.prune_results_older_than(cutoff, dry_run=True) == 1
    assert store.prune_results_older_than(cutoff) == 1
    assert _snapshot(store) == before
    assert store.get_result_for_tenant(calculation_id, tenant_id="tenant-b") is None


def test_capture_clear_and_generic_overwrite_refuse(captured_result):
    store, calculation_id, _ = captured_result
    before = _snapshot(store)
    with pytest.raises(IntegrityError, match="immutable"):
        store.clear_all_records()
    with pytest.raises(IntegrityError, match="immutable"):
        store.record_success(
            calculation_id=calculation_id,
            analytics_type="TWR",
            tenant_id="tenant-a",
            response_payload={"changed": True},
        )
    store.record_failure(
        calculation_id=calculation_id, analytics_type="TWR", tenant_id="tenant-a", error_message="late failure"
    )
    assert _snapshot(store) == before


def test_capture_guard_drift_requires_owner_and_reopen_preserves_original(captured_result):
    store, calculation_id, database_url = captured_result
    before = _snapshot(store)
    with store._engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER trg_composite_result_custody_update")
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(store._engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(DurableSchemaMigrationRequiredError, match="custody_update"):
            store.verify_schema()
        assert all(statement.lstrip().upper().startswith(("SELECT", "PRAGMA")) for statement in statements)
    finally:
        event.remove(store._engine, "before_cursor_execute", observe)
    store.create_schema()
    reopened = AsyncResultStore(database_url)
    try:
        reopened.verify_schema()
        assert _snapshot(reopened) == before
        assert reopened.get_result_for_tenant(calculation_id, tenant_id="tenant-a") is not None
    finally:
        reopened._engine.dispose()


def test_generic_success_and_failure_cannot_create_protected_original(captured_result):
    store, _, _ = captured_result
    before = _snapshot(store)
    with pytest.raises(AsyncResultCaptureAdmissionRequiredError):
        store.record_success(
            calculation_id=uuid4(), analytics_type=CAPTURE_TYPE, tenant_id="tenant-a", response_payload={"forged": True}
        )
    with pytest.raises(AsyncResultCaptureAdmissionRequiredError):
        store.record_failure(
            calculation_id=uuid4(), analytics_type=CAPTURE_TYPE, tenant_id="tenant-a", error_message="forged"
        )
    assert _snapshot(store) == before


def test_ordinary_result_cannot_be_reclassified_as_capture(captured_result):
    store, _, _ = captured_result
    ordinary = uuid4()
    store.record_success(
        calculation_id=ordinary, analytics_type="TWR", tenant_id="tenant-a", response_payload={"ordinary": True}
    )
    before = _snapshot(store)
    with pytest.raises(IntegrityError, match="immutable"):
        with store._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE analytics_async_result SET analytics_type = :purpose WHERE calculation_id = :calculation_id"
                ),
                {"purpose": CAPTURE_TYPE, "calculation_id": str(ordinary)},
            )
    assert _snapshot(store) == before
