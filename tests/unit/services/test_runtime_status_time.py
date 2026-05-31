from datetime import UTC

from app.services.runtime_status_time import age_seconds_since, parse_reclaimed_at_utc, parse_utc_datetime


def test_runtime_status_time_parses_naive_and_offset_timestamps_as_utc():
    assert parse_reclaimed_at_utc("2026-03-15T00:00:00").tzinfo == UTC
    assert parse_utc_datetime("2026-03-15T08:00:00+08:00").isoformat() == "2026-03-15T00:00:00+00:00"


def test_runtime_status_time_clamps_future_age_to_zero():
    assert age_seconds_since("2999-01-01T00:00:00Z") == 0.0
