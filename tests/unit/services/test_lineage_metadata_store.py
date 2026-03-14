from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import event, inspect

from app.services.lineage_metadata_store import (
    LineageMetadataStore,
    LineagePayloadModel,
    LineageRecordModel,
    LineageStatus,
)


def test_lineage_metadata_store_pending_complete_and_failed(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    pending = store.get_record(calculation_id)
    assert pending is not None
    assert pending.status == LineageStatus.PENDING
    assert pending.artifact_names == []

    store.mark_complete(calculation_id=calculation_id, artifact_names=["response.json", "request.json"])
    complete = store.get_record(calculation_id)
    assert complete is not None
    assert complete.status == LineageStatus.COMPLETE
    assert complete.artifact_names == ["request.json", "response.json"]

    store.mark_failed(calculation_id=calculation_id, error_message="write failed")
    failed = store.get_record(calculation_id)
    assert failed is not None
    assert failed.status == LineageStatus.FAILED
    assert failed.error_message == "write failed"


def test_lineage_metadata_store_raises_for_missing_record_updates(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()

    try:
        store.mark_complete(calculation_id=calculation_id, artifact_names=["request.json"])
    except KeyError as exc:
        assert "Lineage record not found" in str(exc)
    else:
        raise AssertionError("Expected mark_complete to raise KeyError")

    try:
        store.mark_failed(calculation_id=calculation_id, error_message="boom")
    except KeyError as exc:
        assert "Lineage record not found" in str(exc)
    else:
        raise AssertionError("Expected mark_failed to raise KeyError")


def test_lineage_metadata_store_payload_queue_roundtrip(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_json='{"request": true}',
        response_json='{"response": true}',
        details={"details.csv": "a,b\n1,2\n"},
    )

    payloads = store.list_pending_payloads(limit=10)
    assert len(payloads) == 1
    assert payloads[0].calculation_id == calculation_id
    assert payloads[0].details == {"details.csv": "a,b\n1,2\n"}
    assert payloads[0].attempt_count == 0

    leased = store.lease_pending_payloads(worker_id="lineage-worker-1", limit=10, lease_seconds=60)
    assert len(leased) == 1
    assert leased[0].attempt_count == 1
    assert leased[0].worker_id == "lineage-worker-1"

    payload = store.get_payload(calculation_id)
    assert payload is not None
    assert payload.attempt_count == 1

    store.delete_payload(calculation_id)
    assert store.list_pending_payloads(limit=10) == []


def test_lineage_metadata_store_raises_when_incrementing_missing_payload(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()

    try:
        store.increment_attempt_count(uuid4())
    except KeyError as exc:
        assert "Lineage payload not found" in str(exc)
    else:
        raise AssertionError("Expected increment_attempt_count to raise KeyError")


def test_lineage_metadata_store_pending_payload_stats(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    now = datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc)

    pending_id = uuid4()
    complete_id = uuid4()

    store.enqueue_lineage_payload(
        calculation_id=pending_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request_payload.json": "request.json"},
    )
    store.enqueue_lineage_payload(
        calculation_id=complete_id,
        calculation_type="MWR",
        request_json="{}",
        response_json="{}",
        details={"response_payload.json": "response.json"},
    )
    store.mark_complete(complete_id, artifact_names=["response_payload.json"])
    failed_id = uuid4()
    store.enqueue_lineage_payload(
        calculation_id=failed_id,
        calculation_type="ATTR",
        request_json="{}",
        response_json="{}",
        details={"details.json": "{}"},
    )
    store.increment_attempt_count(pending_id)
    store.increment_attempt_count(failed_id)
    store.mark_failed(failed_id, error_message="write failed")

    with store._session() as session:
        payload = session.get(LineagePayloadModel, str(pending_id))
        assert payload is not None
        payload.created_at_utc = now - timedelta(seconds=45)

    stats = store.get_pending_payload_stats(now=now)

    assert stats.pending_payload_count == 1
    assert stats.leased_payload_count == 0
    assert stats.retry_backlog_count == 1
    assert stats.terminal_failure_count == 1
    assert stats.oldest_pending_age_seconds == 45.0
    assert stats.oldest_leased_age_seconds == 0.0


def test_lineage_metadata_store_leases_pending_payloads_once_until_expiry(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"details.json": "{}"},
    )

    first_claim = store.lease_pending_payloads(worker_id="lineage-worker-1", limit=10, lease_seconds=60)
    second_claim = store.lease_pending_payloads(worker_id="lineage-worker-2", limit=10, lease_seconds=60)

    assert len(first_claim) == 1
    assert second_claim == []

    with store._session() as session:
        payload = session.get(LineagePayloadModel, str(calculation_id))
        assert payload is not None
        payload.lease_expires_at_utc = datetime.now(timezone.utc) - timedelta(seconds=1)

    reclaimed = store.lease_pending_payloads(worker_id="lineage-worker-2", limit=10, lease_seconds=60)

    assert len(reclaimed) == 1
    assert reclaimed[0].worker_id == "lineage-worker-2"
    assert reclaimed[0].attempt_count == 2


def test_lineage_metadata_store_pending_payload_stats_include_active_leases(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    calculation_id = uuid4()

    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"details.json": "{}"},
    )
    store.lease_pending_payloads(worker_id="lineage-worker-1", limit=10, lease_seconds=60)

    with store._session() as session:
        payload = session.get(LineagePayloadModel, str(calculation_id))
        assert payload is not None
        payload.leased_at_utc = now - timedelta(seconds=15)
        payload.lease_expires_at_utc = now + timedelta(seconds=45)

    stats = store.get_pending_payload_stats(now=now)

    assert stats.pending_payload_count == 1
    assert stats.leased_payload_count == 1
    assert stats.oldest_leased_age_seconds == 15.0


def test_lineage_metadata_store_queue_inspection_anchors(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    pending_id = uuid4()
    leased_id = uuid4()
    failed_id = uuid4()

    for calculation_id in [pending_id, leased_id, failed_id]:
        store.enqueue_lineage_payload(
            calculation_id=calculation_id,
            calculation_type="TWR",
            request_json="{}",
            response_json="{}",
            details={"details.json": "{}"},
        )

    store.mark_failed(failed_id, error_message="boom")

    with store._session() as session:
        pending_payload = session.get(LineagePayloadModel, str(pending_id))
        leased_payload = session.get(LineagePayloadModel, str(leased_id))
        failed_record = session.get(LineageRecordModel, str(failed_id))
        assert pending_payload is not None
        assert leased_payload is not None
        assert failed_record is not None
        pending_payload.created_at_utc = now - timedelta(seconds=120)
        leased_payload.created_at_utc = now - timedelta(seconds=60)
        leased_payload.leased_at_utc = now - timedelta(seconds=90)
        leased_payload.lease_expires_at_utc = now + timedelta(seconds=30)
        failed_record.timestamp_utc = now - timedelta(seconds=5)

    anchors = store.get_queue_inspection_anchors(now=now)

    assert anchors.oldest_pending_calculation_id == str(pending_id)
    assert anchors.oldest_leased_calculation_id == str(leased_id)
    assert anchors.latest_terminal_failure_calculation_id == str(failed_id)


def test_lineage_metadata_store_lists_active_and_failed_inspection_items(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    now = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    pending_id = uuid4()
    leased_id = uuid4()
    failed_id = uuid4()

    for calculation_id in [pending_id, leased_id, failed_id]:
        store.enqueue_lineage_payload(
            calculation_id=calculation_id,
            calculation_type="TWR",
            request_json="{}",
            response_json="{}",
            details={"details.json": "{}"},
        )

    store.mark_failed(failed_id, error_message="boom")

    with store._session() as session:
        pending_payload = session.get(LineagePayloadModel, str(pending_id))
        leased_payload = session.get(LineagePayloadModel, str(leased_id))
        failed_record = session.get(LineageRecordModel, str(failed_id))
        assert pending_payload is not None
        assert leased_payload is not None
        assert failed_record is not None
        pending_payload.created_at_utc = now - timedelta(seconds=120)
        leased_payload.created_at_utc = now - timedelta(seconds=60)
        leased_payload.leased_at_utc = now - timedelta(seconds=90)
        leased_payload.lease_expires_at_utc = now + timedelta(seconds=30)
        failed_record.timestamp_utc = now - timedelta(seconds=10)

    active_page = store.list_inspection_items(status_filter="active", limit=10, now=now)
    failed_page = store.list_inspection_items(status_filter="failed", limit=10, now=now)
    stale_page = store.list_inspection_items(status_filter="active", limit=10, min_age_seconds=100.0, now=now)

    assert active_page.total_count == 2
    assert [item.calculation_id for item in active_page.items] == [str(pending_id), str(leased_id)]
    assert active_page.items[0].status == LineageStatus.PENDING.value
    assert active_page.items[0].age_seconds == 120.0
    assert active_page.items[1].status == "leased"
    assert active_page.items[1].age_seconds == 90.0
    assert failed_page.total_count == 1
    assert len(failed_page.items) == 1
    assert failed_page.items[0].calculation_id == str(failed_id)
    assert failed_page.items[0].status == LineageStatus.FAILED.value
    assert failed_page.items[0].error_message == "boom"
    assert failed_page.items[0].age_seconds == 10.0
    assert stale_page.total_count == 2
    assert [item.calculation_id for item in stale_page.items] == [str(pending_id)]


def test_lineage_metadata_store_filters_inspection_items_by_type_and_calculation_substring(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    ids = [uuid4() for _ in range(3)]
    types = ["TWR", "Attribution", "TWR"]

    for calculation_id, calculation_type in zip(ids, types, strict=True):
        store.enqueue_lineage_payload(
            calculation_id=calculation_id,
            calculation_type=calculation_type,
            request_json="{}",
            response_json="{}",
            details={"details.json": "{}"},
        )

    filtered = store.list_inspection_items(
        status_filter="all",
        limit=10,
        calculation_type="TWR",
        calculation_id_contains=str(ids[2])[:8],
    )

    assert filtered.total_count == 1
    assert [item.calculation_id for item in filtered.items] == [str(ids[2])]


def test_lineage_metadata_store_mark_pending_clears_error(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.create_pending_record(calculation_id=calculation_id, calculation_type="TWR")
    store.mark_failed(calculation_id=calculation_id, error_message="boom")
    store.mark_pending(calculation_id=calculation_id)

    record = store.get_record(calculation_id)
    assert record is not None
    assert record.status == LineageStatus.PENDING
    assert record.error_message is None
    payload = store.get_payload(calculation_id)
    assert payload is None


def test_lineage_metadata_store_mark_pending_releases_payload_lease(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()

    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"details.json": "{}"},
    )
    store.lease_pending_payloads(worker_id="lineage-worker-1", limit=10, lease_seconds=60)

    store.mark_pending(calculation_id=calculation_id)

    payload = store.get_payload(calculation_id)
    assert payload is not None
    assert payload.worker_id is None
    assert payload.leased_at_utc is None
    assert payload.lease_expires_at_utc is None


def test_lineage_metadata_store_declares_hot_path_indexes(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()

    record_indexes = {
        index["name"]: tuple(index["column_names"]) for index in inspect(store._engine).get_indexes("lineage_records")
    }
    payload_indexes = {
        index["name"]: tuple(index["column_names"]) for index in inspect(store._engine).get_indexes("lineage_payloads")
    }

    assert record_indexes["ix_lineage_records_status"] == ("status",)
    assert payload_indexes["ix_lineage_payloads_created_at"] == ("created_at_utc",)
    assert payload_indexes["ix_lineage_payloads_lease_expires_at"] == ("lease_expires_at_utc",)


def test_lineage_metadata_store_get_pending_payload_stats_uses_single_aggregate_query(tmp_path):
    store = LineageMetadataStore(f"sqlite:///{tmp_path / 'lineage.db'}")
    store.create_schema()
    calculation_id = uuid4()
    now = datetime.now(timezone.utc)
    store.enqueue_lineage_payload(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request.json": "{}"},
    )

    statements: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(store._engine, "before_cursor_execute", _before_cursor_execute)
    try:
        stats = store.get_pending_payload_stats(now=now)
    finally:
        event.remove(store._engine, "before_cursor_execute", _before_cursor_execute)

    assert stats.pending_payload_count == 1
    select_statements = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
    assert len(select_statements) == 1


def test_lineage_metadata_store_create_schema_migrates_existing_payload_table(tmp_path):
    database_path = tmp_path / "lineage_legacy.db"
    store = LineageMetadataStore(f"sqlite:///{database_path}")

    with store._engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE lineage_records (
                calculation_id VARCHAR(36) PRIMARY KEY,
                calculation_type VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                timestamp_utc DATETIME NOT NULL,
                artifact_names TEXT NOT NULL DEFAULT '',
                error_message TEXT
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE lineage_payloads (
                calculation_id VARCHAR(36) PRIMARY KEY,
                calculation_type VARCHAR(64) NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at_utc DATETIME NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    store.create_schema()

    payload_columns = {column["name"] for column in inspect(store._engine).get_columns("lineage_payloads")}
    payload_indexes = {
        index["name"]: tuple(index["column_names"]) for index in inspect(store._engine).get_indexes("lineage_payloads")
    }

    assert {"worker_id", "leased_at_utc", "lease_expires_at_utc"}.issubset(payload_columns)
    assert payload_indexes["ix_lineage_payloads_lease_expires_at"] == ("lease_expires_at_utc",)
