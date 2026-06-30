import pytest
from fastapi import HTTPException

from app.api.dependencies.runtime_retention_history import build_runtime_retention_history_query


def test_build_runtime_retention_history_query_projects_filters_and_validates_timestamp_window():
    query = build_runtime_retention_history_query(
        limit=25,
        offset=5,
        operator_id="ops-user",
        trigger_mode="manual",
        job_id="ticket-123",
        cleanup_mode="dry_run",
        status="completed",
        generated_after="2026-03-14T00:00:00Z",
        generated_before="2026-03-15T00:00:00Z",
    )

    assert query.model_dump() == {
        "limit": 25,
        "offset": 5,
        "operator_id": "ops-user",
        "trigger_mode": "manual",
        "job_id": "ticket-123",
        "cleanup_mode": "dry_run",
        "status": "completed",
        "generated_after": "2026-03-14T00:00:00Z",
        "generated_before": "2026-03-15T00:00:00Z",
    }


def test_build_runtime_retention_history_query_defaults_to_bounded_first_page():
    query = build_runtime_retention_history_query()

    assert query.model_dump() == {
        "limit": 10,
        "offset": 0,
        "operator_id": None,
        "trigger_mode": None,
        "job_id": None,
        "cleanup_mode": None,
        "status": None,
        "generated_after": None,
        "generated_before": None,
    }


def test_build_runtime_retention_history_query_rejects_inverted_timestamp_window():
    with pytest.raises(HTTPException) as exc_info:
        build_runtime_retention_history_query(
            generated_after="2026-03-16T00:00:00Z",
            generated_before="2026-03-15T00:00:00Z",
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {
        "code": "invalid_utc_timestamp_filter_window",
        "fields": ["generated_after", "generated_before"],
        "message": "generated_after must be less than or equal to generated_before.",
    }
