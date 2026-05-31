from datetime import UTC, datetime, timedelta, timezone

from app.services.durable_store_time import (
    coerce_utc_datetime,
    elapsed_seconds_since,
    format_timestamp,
    normalize_filter_datetime,
)


def test_durable_store_time_formats_naive_and_offset_timestamps_as_utc():
    assert format_timestamp(datetime(2026, 3, 15, 0, 0, 0)) == "2026-03-15T00:00:00Z"
    offset_timestamp = datetime(2026, 3, 15, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert format_timestamp(offset_timestamp) == "2026-03-15T00:00:00Z"
    assert coerce_utc_datetime(offset_timestamp).tzinfo == UTC


def test_durable_store_time_normalizes_sqlite_filter_to_naive_utc():
    timestamp = datetime.fromisoformat("2026-03-15T08:00:00+08:00")

    sqlite_value = normalize_filter_datetime(timestamp, dialect_name="sqlite")
    postgres_value = normalize_filter_datetime(timestamp, dialect_name="postgresql")

    assert sqlite_value == datetime(2026, 3, 15, 0, 0, 0)
    assert sqlite_value.tzinfo is None
    assert postgres_value == datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)


def test_durable_store_time_clamps_elapsed_seconds_for_future_timestamps():
    now = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)

    assert elapsed_seconds_since(now, datetime(2026, 3, 14, 23, 59, 0)) == 60.0
    assert elapsed_seconds_since(now, datetime(2026, 3, 15, 0, 1, 0, tzinfo=UTC)) == 0.0
