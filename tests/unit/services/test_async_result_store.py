from datetime import datetime, timezone
from uuid import uuid4

from app.services.async_result_store import (
    INVALID_ASYNC_RESULT_PAYLOAD_ERROR_TYPE,
    INVALID_ASYNC_RESULT_PAYLOAD_MESSAGE,
    AsyncResultModel,
    AsyncResultStatus,
    AsyncResultStore,
    _async_result_record_payload_state,
    _has_invalid_response_payload,
)


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
