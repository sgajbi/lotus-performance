from datetime import datetime, timezone
from uuid import uuid4

from app.services.async_result_store import AsyncResultModel, AsyncResultStatus, AsyncResultStore


def test_async_result_store_records_success_and_failure(tmp_path):
    store = AsyncResultStore(f"sqlite:///{tmp_path / 'async_results.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.record_success(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        response_payload={"calculation_id": str(calculation_id), "status": "ok"},
    )
    success = store.get_result(calculation_id)
    assert success is not None
    assert success.result_status == AsyncResultStatus.COMPLETE
    assert success.response_payload == {"calculation_id": str(calculation_id), "status": "ok"}

    store.record_failure(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        error_message="boom",
        error_type="RuntimeError",
    )
    failure = store.get_result(calculation_id)
    assert failure is not None
    assert failure.result_status == AsyncResultStatus.FAILED
    assert failure.response_payload is None
    assert failure.error_message == "boom"
    assert failure.error_type == "RuntimeError"


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
