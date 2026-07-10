from datetime import UTC, datetime

from app.api.dependencies.runtime_recoveries import build_runtime_recoveries_query


def test_build_runtime_recoveries_query_projects_filters():
    recovered_after = datetime(2026, 3, 14, 12, tzinfo=UTC)
    recovered_before = datetime(2026, 3, 15, 12, tzinfo=UTC)
    cursor_recovered_before = datetime(2026, 3, 15, 10, tzinfo=UTC)

    query = build_runtime_recoveries_query(
        queue="compute",
        limit=25,
        offset=5,
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        cursor_recovered_before=cursor_recovered_before,
        cursor_calculation_id_before="calc-123",
        compute_analytics_type="ReturnsSeries",
        lineage_calculation_type="TWR",
        calculation_id_contains="ABCDEF12",
    )

    assert query.model_dump() == {
        "queue": "compute",
        "limit": 25,
        "offset": 5,
        "recovered_after": recovered_after,
        "recovered_before": recovered_before,
        "cursor_recovered_before": cursor_recovered_before,
        "cursor_calculation_id_before": "calc-123",
        "compute_analytics_type": "ReturnsSeries",
        "lineage_calculation_type": "TWR",
        "calculation_id_contains": "abcdef12",
    }


def test_build_runtime_recoveries_query_defaults_to_both_queues_first_page():
    query = build_runtime_recoveries_query()

    assert query.model_dump() == {
        "queue": "both",
        "limit": 10,
        "offset": 0,
        "recovered_after": None,
        "recovered_before": None,
        "cursor_recovered_before": None,
        "cursor_calculation_id_before": None,
        "compute_analytics_type": None,
        "lineage_calculation_type": None,
        "calculation_id_contains": None,
    }
