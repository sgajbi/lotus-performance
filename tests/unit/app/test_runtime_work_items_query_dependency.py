from app.api.dependencies.runtime_work_items import build_runtime_work_items_query


def test_build_runtime_work_items_query_projects_filters():
    query = build_runtime_work_items_query(
        queue="lineage",
        status="reclaimable",
        limit=25,
        offset=5,
        min_age_seconds=120.5,
        compute_analytics_type="ReturnsSeries",
        lineage_calculation_type="TWR",
        calculation_id_contains="ABCDEF12",
    )

    assert query.model_dump() == {
        "queue": "lineage",
        "status": "reclaimable",
        "limit": 25,
        "offset": 5,
        "min_age_seconds": 120.5,
        "compute_analytics_type": "ReturnsSeries",
        "lineage_calculation_type": "TWR",
        "calculation_id_contains": "abcdef12",
    }


def test_build_runtime_work_items_query_defaults_to_active_both_queues_first_page():
    query = build_runtime_work_items_query()

    assert query.model_dump() == {
        "queue": "both",
        "status": "active",
        "limit": 10,
        "offset": 0,
        "min_age_seconds": 0.0,
        "compute_analytics_type": None,
        "lineage_calculation_type": None,
        "calculation_id_contains": None,
    }
