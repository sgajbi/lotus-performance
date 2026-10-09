from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import DBAPIError

from app.adapters.composite_pooled_mwr_repository import CompositePooledMWRInputStore
from app.adapters.composite_result_custody_schema import COMPOSITE_POOLED_ANALYTICS_TYPE
from app.models.composite_pooled_mwr import PooledSourceBundle
from app.services.async_result_store import (
    INVALID_ASYNC_RESULT_PAYLOAD_ERROR_TYPE,
    INVALID_ASYNC_RESULT_PAYLOAD_MESSAGE,
    AsyncResultCaptureAdmissionRequiredError,
    AsyncResultModel,
    AsyncResultOriginalConflictError,
    AsyncResultStatus,
    AsyncResultStore,
    AsyncResultTenantConflictError,
    _async_result_record_payload_state,
    _has_invalid_response_payload,
)
from app.services.composite_pooled_mwr.admission import admit_pooled_observation
from app.services.durable_failure_classification import classify_durable_failure
from core.errors import APIUnprocessableEntityError
from tests.unit.services.test_composite_pooled_mwr_admission import controlled_request, controlled_source_payload


@pytest.fixture
def pooled_result_custody(tmp_path):
    url = f"sqlite:///{tmp_path / 'pooled-results.db'}"
    inputs = CompositePooledMWRInputStore(url)
    inputs.create_schema()
    results = AsyncResultStore(url)
    results.create_schema()
    engine = create_engine(url)
    request = controlled_request()
    observation = admit_pooled_observation(
        request, PooledSourceBundle.model_validate(controlled_source_payload()), tenant_id="controlled-tenant"
    )
    with engine.begin() as connection:
        inputs.bind(connection, tenant_id="controlled-tenant", request=request, observation=observation)
    payload = {
        "calculation_id": str(request.calculation_id),
        "input_manifest_digest": observation.input_manifest_digest,
        "controlled_result": "0.10",
    }
    yield results, engine, request, observation, payload
    engine.dispose()
    inputs.close()
    results._engine.dispose()


def _publish_pooled(results, connection, request, observation, payload, **change):
    results.record_pooled_success_in_transaction(
        connection,
        **{
            "calculation_id": request.calculation_id,
            "tenant_id": "controlled-tenant",
            "input_manifest_digest": observation.input_manifest_digest,
            "response_payload": payload,
            **change,
        },
    )


def test_pooled_original_retry_replays_without_update(pooled_result_custody):
    results, engine, request, observation, payload = pooled_result_custody
    statements = []
    event.listen(engine, "before_cursor_execute", lambda _, __, sql, *args: statements.append(sql))
    with engine.begin() as connection:
        _publish_pooled(results, connection, request, observation, payload)
    original = results.get_result(request.calculation_id)
    with engine.begin() as connection:
        _publish_pooled(results, connection, request, observation, dict(reversed(list(payload.items()))))
    assert results.get_result(request.calculation_id) == original
    assert original.response_payload == payload
    assert not any(sql.lstrip().upper().startswith("UPDATE") for sql in statements)


@pytest.mark.parametrize("change", ["payload", "tenant", "digest", "calculation"])
def test_pooled_original_conflicts_preserve_original(pooled_result_custody, change):
    results, engine, request, observation, payload = pooled_result_custody
    with engine.begin() as connection:
        _publish_pooled(results, connection, request, observation, payload)
    original = results.get_result(request.calculation_id)
    override = {
        "payload": {"response_payload": {**payload, "controlled_result": "0.20"}},
        "tenant": {"tenant_id": "foreign"},
        "digest": {"input_manifest_digest": "wrong"},
        "calculation": {"calculation_id": uuid4()},
    }[change]
    with pytest.raises(AsyncResultOriginalConflictError):
        with engine.begin() as connection:
            _publish_pooled(results, connection, request, observation, payload, **override)
    assert results.get_result(request.calculation_id) == original


def test_pooled_original_transaction_rollback_and_retry(pooled_result_custody):
    results, engine, request, observation, payload = pooled_result_custody
    with pytest.raises(RuntimeError, match="interrupted"):
        with engine.begin() as connection:
            _publish_pooled(results, connection, request, observation, payload)
            raise RuntimeError("interrupted publication")
    assert results.get_result(request.calculation_id) is None
    with engine.begin() as connection:
        _publish_pooled(results, connection, request, observation, payload)
    assert results.get_result(request.calculation_id).response_payload == payload


def test_pooled_original_cannot_repurpose_existing_ordinary_result(pooled_result_custody):
    results, engine, request, observation, payload = pooled_result_custody
    results.record_success(
        calculation_id=request.calculation_id,
        tenant_id="controlled-tenant",
        analytics_type="TWR",
        response_payload=payload,
    )
    original = results.get_result(request.calculation_id)
    with pytest.raises(AsyncResultOriginalConflictError):
        with engine.begin() as connection:
            _publish_pooled(results, connection, request, observation, payload)
    assert results.get_result(request.calculation_id) == original


@pytest.mark.parametrize("operation", ["success", "failure"])
def test_pooled_generic_writes_refuse_including_operational_failure(pooled_result_custody, operation):
    results, _, request, _, payload = pooled_result_custody
    with pytest.raises(AsyncResultCaptureAdmissionRequiredError):
        if operation == "success":
            results.record_success(
                calculation_id=request.calculation_id,
                tenant_id="controlled-tenant",
                analytics_type=COMPOSITE_POOLED_ANALYTICS_TYPE,
                response_payload=payload,
            )
        else:
            results.record_failure(
                calculation_id=request.calculation_id,
                tenant_id="controlled-tenant",
                analytics_type=COMPOSITE_POOLED_ANALYTICS_TYPE,
                error_message="retryable failure",
            )
    assert results.get_result(request.calculation_id) is None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE analytics_async_result SET response_json='{}'",
        "UPDATE analytics_async_result SET analytics_type='TWR'",
        "UPDATE analytics_async_result SET tenant_id='foreign'",
        "DELETE FROM analytics_async_result",
    ],
)
def test_pooled_original_sql_guard_refuses_mutation(pooled_result_custody, statement):
    results, engine, request, observation, payload = pooled_result_custody
    with engine.begin() as connection:
        _publish_pooled(results, connection, request, observation, payload)
    original = results.get_result(request.calculation_id)
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(text(statement))
    assert results.get_result(request.calculation_id) == original
    results.verify_schema()


def test_pooled_original_retention_excludes_financial_original_but_prunes_ordinary(pooled_result_custody):
    from datetime import timedelta

    results, engine, request, observation, payload = pooled_result_custody
    with engine.begin() as connection:
        _publish_pooled(results, connection, request, observation, payload)
    ordinary = uuid4()
    results.record_success(calculation_id=ordinary, analytics_type="TWR", response_payload={"ok": True})
    cutoff = datetime.now(timezone.utc) + timedelta(days=1)
    assert results.list_result_ids_older_than(cutoff) == [str(ordinary)]
    assert results.prune_results_older_than(cutoff, dry_run=True) == 1
    assert results.prune_results_older_than(cutoff) == 1
    assert results.get_result(request.calculation_id).response_payload == payload


def test_pooled_sql_cannot_repurpose_ordinary_result(pooled_result_custody):
    results, engine, request, _, payload = pooled_result_custody
    results.record_success(calculation_id=request.calculation_id, analytics_type="TWR", response_payload=payload)
    original = results.get_result(request.calculation_id)
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE analytics_async_result SET analytics_type='COMPOSITE_POOLED_MWR'"))
    assert results.get_result(request.calculation_id) == original


def test_async_result_store_records_success_and_failure(tmp_path):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    success_calculation_id = uuid4()
    failure_calculation_id = uuid4()

    store.record_success(
        calculation_id=success_calculation_id,
        analytics_type="ReturnsSeries",
        response_payload={"calculation_id": str(success_calculation_id), "status": "ok"},
    )
    success = store.get_result(success_calculation_id)
    assert success is not None
    assert success.result_status == AsyncResultStatus.COMPLETE
    assert success.response_payload == {"calculation_id": str(success_calculation_id), "status": "ok"}

    store.record_failure(
        calculation_id=failure_calculation_id,
        analytics_type="ReturnsSeries",
        error_message="boom",
        error_type="RuntimeError",
    )
    failure = store.get_result(failure_calculation_id)
    assert failure is not None
    assert failure.result_status == AsyncResultStatus.FAILED
    assert failure.response_payload is None
    assert failure.error_message == "boom"
    assert failure.error_type == "RuntimeError"


def test_async_result_store_round_trips_governed_failure_after_reopen(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'async_results.db'}"
    store = AsyncResultStore(database_url)
    store.create_schema()
    calculation_id = uuid4()
    classification = classify_durable_failure(
        APIUnprocessableEntityError("Window is too large.", error_code="HISTORY_WINDOW_TOO_LARGE")
    )
    store.record_failure(
        calculation_id=calculation_id,
        tenant_id="tenant-a",
        analytics_type="TWR",
        error_message=classification.message,
        error_type="APIUnprocessableEntityError",
        failure=classification,
    )

    reopened = AsyncResultStore(database_url)
    reopened.create_schema()
    result = reopened.get_result_for_tenant(calculation_id, tenant_id="tenant-a")

    assert result is not None
    assert result.failure == classification


def test_async_result_store_schema_bootstrap_adds_failure_to_legacy_table(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy-async-results.db'}"
    store = AsyncResultStore(database_url)
    with store._engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE analytics_async_result ("
                "calculation_id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(128), "
                "analytics_type VARCHAR(64) NOT NULL, result_status VARCHAR(32) NOT NULL, "
                "response_json TEXT, error_message TEXT, error_type VARCHAR(128), "
                "created_at_utc DATETIME NOT NULL, updated_at_utc DATETIME NOT NULL)"
            )
        )

    store.create_schema()

    columns = {column["name"] for column in inspect(store._engine).get_columns("analytics_async_result")}
    assert "failure_json" in columns


def test_async_result_store_scopes_reads_and_rejects_cross_tenant_overwrite(tmp_path):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    calculation_id = uuid4()
    store.record_success(
        calculation_id=calculation_id,
        tenant_id="tenant-a",
        analytics_type="ReturnsSeries",
        response_payload={"owner": "tenant-a"},
    )

    assert store.get_result_for_tenant(calculation_id, tenant_id="tenant-a") is not None
    assert store.get_result_for_tenant(calculation_id, tenant_id="tenant-b") is None
    with pytest.raises(AsyncResultTenantConflictError, match="different tenant"):
        store.record_failure(
            calculation_id=calculation_id,
            tenant_id="tenant-b",
            analytics_type="ReturnsSeries",
            error_message="cross-tenant mutation",
        )

    result = store.get_result_for_tenant(calculation_id, tenant_id="tenant-a")
    assert result is not None
    assert result.response_payload == {"owner": "tenant-a"}


def test_async_result_store_preserves_success_when_late_failure_is_recorded(tmp_path, caplog):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    calculation_id = uuid4()
    response_payload = {"calculation_id": str(calculation_id), "status": "ok"}
    store.record_success(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        response_payload=response_payload,
    )

    with caplog.at_level("WARNING", logger="app.services.async_result_store"):
        store.record_failure(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            error_message="late finalization failure",
            error_type="RuntimeError",
        )

    result = store.get_result(calculation_id)
    assert result is not None
    assert result.result_status == AsyncResultStatus.COMPLETE
    assert result.response_payload == response_payload
    assert result.error_message is None
    assert result.error_type is None
    assert "Skipped async result failure write because a success result already exists." in caplog.text


def test_async_result_store_formats_sqlite_timestamps_as_utc(tmp_path):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    calculation_id = uuid4()
    created_at = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    updated_at = datetime(2026, 3, 14, 12, 30, tzinfo=timezone.utc)

    with store._session() as session:
        session.merge(
            AsyncResultModel(
                calculation_id=str(calculation_id),
                analytics_type="ReturnsSeries",
                result_status=AsyncResultStatus.COMPLETE.value,
                response_json='{"ok": true}',
                error_message=None,
                error_type=None,
                created_at_utc=created_at,
                updated_at_utc=updated_at,
            )
        )

    result = store.get_result(calculation_id)

    assert result is not None
    assert result.created_at_utc == "2026-03-14T12:00:00Z"
    assert result.updated_at_utc == "2026-03-14T12:30:00Z"


def test_async_result_store_fails_closed_on_invalid_response_json(tmp_path, caplog):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    calculation_id = uuid4()
    created_at = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    with store._session() as session:
        session.merge(
            AsyncResultModel(
                calculation_id=str(calculation_id),
                analytics_type="ReturnsSeries",
                result_status=AsyncResultStatus.COMPLETE.value,
                response_json="{not-json",
                error_message=None,
                error_type=None,
                created_at_utc=created_at,
                updated_at_utc=created_at,
            )
        )

    with caplog.at_level("WARNING", logger="app.services.async_result_store"):
        result = store.get_result(calculation_id)

    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED
    assert result.response_payload is None
    assert result.error_message == INVALID_ASYNC_RESULT_PAYLOAD_MESSAGE
    assert result.error_type == INVALID_ASYNC_RESULT_PAYLOAD_ERROR_TYPE
    assert f"calculation_id={calculation_id}" in caplog.text


def test_async_result_store_fails_closed_on_non_object_response_json(tmp_path, caplog):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    calculation_id = uuid4()
    created_at = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)

    with store._session() as session:
        session.merge(
            AsyncResultModel(
                calculation_id=str(calculation_id),
                analytics_type="ReturnsSeries",
                result_status=AsyncResultStatus.COMPLETE.value,
                response_json="[1, 2, 3]",
                error_message=None,
                error_type=None,
                created_at_utc=created_at,
                updated_at_utc=created_at,
            )
        )

    with caplog.at_level("WARNING", logger="app.services.async_result_store"):
        result = store.get_result(calculation_id)

    assert result is not None
    assert result.result_status == AsyncResultStatus.FAILED
    assert result.response_payload is None
    assert result.error_type == INVALID_ASYNC_RESULT_PAYLOAD_ERROR_TYPE
    assert f"calculation_id={calculation_id}" in caplog.text


def test_async_result_payload_state_preserves_existing_failure_details_for_invalid_payload():
    calculation_id = uuid4()
    row = AsyncResultModel(
        calculation_id=str(calculation_id),
        analytics_type="ReturnsSeries",
        result_status=AsyncResultStatus.COMPLETE.value,
        response_json="{not-json",
        error_message="existing failure",
        error_type="ExistingFailure",
        created_at_utc=datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc),
        updated_at_utc=datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc),
    )

    payload_state = _async_result_record_payload_state(row, response_payload=None)

    assert payload_state.result_status == AsyncResultStatus.FAILED
    assert payload_state.response_payload is None
    assert payload_state.error_message == "existing failure"
    assert payload_state.error_type == "ExistingFailure"


def test_has_invalid_response_payload_requires_source_json_without_loaded_payload():
    calculation_id = uuid4()
    row = AsyncResultModel(
        calculation_id=str(calculation_id),
        analytics_type="ReturnsSeries",
        result_status=AsyncResultStatus.COMPLETE.value,
        response_json="{not-json",
        error_message=None,
        error_type=None,
        created_at_utc=datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc),
        updated_at_utc=datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert _has_invalid_response_payload(row, response_payload=None)
    assert not _has_invalid_response_payload(row, response_payload={"ok": True})

    row.response_json = None
    assert not _has_invalid_response_payload(row, response_payload=None)


def test_async_result_store_prunes_results_older_than_cutoff(tmp_path):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    old_id = uuid4()
    recent_id = uuid4()

    store.record_success(
        calculation_id=old_id,
        analytics_type="ReturnsSeries",
        response_payload={"ok": True},
    )
    store.record_success(
        calculation_id=recent_id,
        analytics_type="ReturnsSeries",
        response_payload={"ok": True},
    )

    with store._session() as session:
        old_row = session.get(AsyncResultModel, str(old_id))
        recent_row = session.get(AsyncResultModel, str(recent_id))
        assert old_row is not None
        assert recent_row is not None
        old_row.updated_at_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
        recent_row.updated_at_utc = datetime(2026, 3, 10, tzinfo=timezone.utc)

    cutoff = datetime(2026, 2, 1, tzinfo=timezone.utc)

    assert store.prune_results_older_than(cutoff, dry_run=True) == 1
    assert store.prune_results_older_than(cutoff, dry_run=False) == 1
    assert store.get_result(old_id) is None
    assert store.get_result(recent_id) is not None


def test_async_result_store_declares_retention_index(tmp_path):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()

    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspect(store._engine).get_indexes("analytics_async_result")
    }

    assert indexes["ix_async_result_updated_at"] == ("updated_at_utc",)


def test_async_result_store_prune_uses_count_and_set_based_delete(tmp_path):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    old_id = uuid4()
    recent_id = uuid4()

    for calculation_id in (old_id, recent_id):
        store.record_success(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            response_payload={"calculation_id": str(calculation_id)},
        )

    with store._session() as session:
        old_row = session.get(AsyncResultModel, str(old_id))
        recent_row = session.get(AsyncResultModel, str(recent_id))
        assert old_row is not None
        assert recent_row is not None
        old_row.updated_at_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
        recent_row.updated_at_utc = datetime(2026, 3, 10, tzinfo=timezone.utc)

    statements: list[str] = []

    @event.listens_for(store._engine, "before_cursor_execute")
    def _capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    cutoff = datetime(2026, 2, 1, tzinfo=timezone.utc)

    assert store.prune_results_older_than(cutoff, dry_run=True) == 1
    assert store.prune_results_older_than(cutoff, dry_run=False) == 1

    assert any("count" in statement and "analytics_async_result" in statement for statement in statements)
    assert any(statement.lstrip().startswith("delete from analytics_async_result") for statement in statements)
    assert not any("response_json" in statement for statement in statements)
