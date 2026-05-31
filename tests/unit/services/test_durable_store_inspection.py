from datetime import datetime, timezone

from app.services.durable_store_inspection import build_inspection_query_context


def test_build_inspection_query_context_normalizes_status_and_age_threshold():
    now = datetime(2026, 5, 31, 10, 30, tzinfo=timezone.utc)

    context = build_inspection_query_context(status_filter="Active", min_age_seconds=120.0, now=now)

    assert context.status_filter == "active"
    assert context.now == now
    assert context.min_age_threshold == datetime(2026, 5, 31, 10, 28, tzinfo=timezone.utc)


def test_build_inspection_query_context_omits_non_positive_age_threshold():
    now = datetime(2026, 5, 31, 10, 30, tzinfo=timezone.utc)

    zero_context = build_inspection_query_context(status_filter="failed", min_age_seconds=0.0, now=now)
    negative_context = build_inspection_query_context(status_filter="failed", min_age_seconds=-1.0, now=now)

    assert zero_context.min_age_threshold is None
    assert negative_context.min_age_threshold is None
