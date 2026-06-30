from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.services.compute_job_store import compute_job_store
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.runtime_operator_diagnostics import COMPUTE_RECOVERY_READ_FAILED
from main import app


def test_runtime_recoveries_returns_filtered_events():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    now = datetime.now(timezone.utc)
    compute_id = uuid4()
    lineage_id = uuid4()

    compute_job_store.enqueue_job(
        calculation_id=compute_id,
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-1"},
    )
    with compute_job_store._session() as session:
        row = compute_job_store._get_model(session, compute_id)
        row.attempt_count = 1
        row.last_error_at_utc = now - timedelta(seconds=5)

    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=lineage_id,
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"details.json": "{}"},
    )
    lineage_metadata_store.increment_attempt_count(lineage_id)
    lineage_metadata_store.mark_pending(lineage_id)

    try:
        with TestClient(app) as client:
            response = client.get(
                "/integration/runtime-recoveries",
                params={
                    "queue": "both",
                    "limit": 1,
                    "compute_analytics_type": "ReturnsSeries",
                    "lineage_calculation_type": "TWR",
                    "recovered_after": (now - timedelta(seconds=30)).isoformat(),
                    "recovered_before": (now + timedelta(seconds=5)).isoformat(),
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["queue_filter"] == "both"
        assert body["compute_queue"]["total_count"] == 1
        assert body["lineage_queue"]["total_count"] == 1
        assert body["compute_queue"]["next_offset"] is None
        assert body["lineage_queue"]["next_offset"] is None
        assert body["recovered_after"] is not None
        assert body["recovered_before"] is not None
        assert body["compute_recoveries"][0]["calculation_id"] == str(compute_id)
        assert body["compute_recoveries"][0]["execution_path"] == f"/performance/executions/{compute_id}"
        assert body["compute_recoveries"][0]["lineage_path"] == f"/performance/lineage/{compute_id}"
        assert body["compute_recoveries"][0]["result_path"] == f"/integration/returns/series/results/{compute_id}"
        assert body["lineage_recoveries"][0]["calculation_id"] == str(lineage_id)
        assert body["lineage_recoveries"][0]["execution_path"] == f"/performance/executions/{lineage_id}"
        assert body["lineage_recoveries"][0]["lineage_path"] == f"/performance/lineage/{lineage_id}"
        assert body["lineage_recoveries"][0]["result_path"] == f"/performance/twr/results/{lineage_id}"
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()


def test_runtime_recoveries_returns_next_offset_for_additional_matching_events():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    now = datetime.now(timezone.utc)
    compute_ids = [uuid4(), uuid4()]

    for seconds_ago, calculation_id in zip([20, 10], compute_ids, strict=True):
        compute_job_store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": str(calculation_id)},
        )
        with compute_job_store._session() as session:
            row = compute_job_store._get_model(session, calculation_id)
            row.attempt_count = 1
            row.last_error_at_utc = now - timedelta(seconds=seconds_ago)

    try:
        with TestClient(app) as client:
            response = client.get("/integration/runtime-recoveries", params={"queue": "compute", "limit": 1})

        assert response.status_code == 200
        body = response.json()
        assert body["compute_queue"]["total_count"] == 2
        assert body["compute_queue"]["returned_count"] == 1
        assert body["compute_queue"]["next_offset"] == 1
        assert body["compute_queue"]["next_cursor_recovered_before"] is not None
        assert body["compute_queue"]["next_cursor_calculation_id_before"] == str(compute_ids[1])
        assert body["lineage_queue"]["status"] == "excluded"
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()


def test_runtime_recoveries_exposes_result_paths_for_twr_and_benchmark_jobs():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    now = datetime.now(timezone.utc)
    twr_id = uuid4()
    benchmark_id = uuid4()

    for analytics_type, calculation_id in [("TWR", twr_id), ("BENCHMARK", benchmark_id)]:
        compute_job_store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type=analytics_type,
            request_payload={"id": str(calculation_id)},
        )
        with compute_job_store._session() as session:
            row = compute_job_store._get_model(session, calculation_id)
            row.attempt_count = 1
            row.last_error_at_utc = now - timedelta(seconds=5)

    try:
        with TestClient(app) as client:
            twr_response = client.get(
                "/integration/runtime-recoveries",
                params={"queue": "compute", "limit": 5, "compute_analytics_type": "TWR"},
            )
            benchmark_response = client.get(
                "/integration/runtime-recoveries",
                params={"queue": "compute", "limit": 5, "compute_analytics_type": "BENCHMARK"},
            )

        assert twr_response.status_code == 200
        assert benchmark_response.status_code == 200
        assert twr_response.json()["compute_recoveries"][0]["result_path"] == f"/performance/twr/results/{twr_id}"
        assert benchmark_response.json()["compute_recoveries"][0]["result_path"] == (
            f"/performance/benchmark/results/{benchmark_id}"
        )
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()


def test_runtime_recoveries_exposes_result_path_for_benchmark_lineage_events():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    benchmark_lineage_id = uuid4()

    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=benchmark_lineage_id,
        calculation_type="BENCHMARK",
        request_json="{}",
        response_json="{}",
        details={"details.json": "{}"},
    )
    lineage_metadata_store.increment_attempt_count(benchmark_lineage_id)
    lineage_metadata_store.mark_pending(benchmark_lineage_id)

    try:
        with TestClient(app) as client:
            response = client.get(
                "/integration/runtime-recoveries",
                params={"queue": "lineage", "limit": 5, "lineage_calculation_type": "BENCHMARK"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["lineage_recoveries"][0]["result_path"] == (
            f"/performance/benchmark/results/{benchmark_lineage_id}"
        )
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()


def test_runtime_recoveries_rejects_blank_string_filters():
    with TestClient(app) as client:
        response = client.get(
            "/integration/runtime-recoveries",
            params={"lineage_calculation_type": " ", "cursor_calculation_id_before": "  "},
        )

    assert response.status_code == 422
    fields = {item["loc"][-1] for item in response.json()["validation_errors"]}
    assert {"lineage_calculation_type", "cursor_calculation_id_before"} <= fields


def test_runtime_recoveries_rejects_inverted_time_window():
    with TestClient(app) as client:
        response = client.get(
            "/integration/runtime-recoveries",
            params={
                "recovered_after": "2026-03-14T12:00:00Z",
                "recovered_before": "2026-03-14T00:00:00Z",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_recovery_time_window"


def test_runtime_recoveries_rejects_incomplete_cursor():
    with TestClient(app) as client:
        response = client.get(
            "/integration/runtime-recoveries",
            params={"cursor_calculation_id_before": "calc-1"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "incomplete_recovery_cursor"


def test_runtime_recoveries_supports_seek_cursor_pagination():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()
    now = datetime.now(timezone.utc)
    compute_ids = [uuid4(), uuid4(), uuid4()]

    for seconds_ago, calculation_id in zip([30, 20, 10], compute_ids, strict=True):
        compute_job_store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"portfolio_id": str(calculation_id)},
        )
        with compute_job_store._session() as session:
            row = compute_job_store._get_model(session, calculation_id)
            row.attempt_count = 1
            row.last_error_at_utc = now - timedelta(seconds=seconds_ago)

    try:
        with TestClient(app) as client:
            first_response = client.get("/integration/runtime-recoveries", params={"queue": "compute", "limit": 1})
            first_body = first_response.json()
            second_response = client.get(
                "/integration/runtime-recoveries",
                params={
                    "queue": "compute",
                    "limit": 1,
                    "cursor_recovered_before": first_body["compute_queue"]["next_cursor_recovered_before"],
                    "cursor_calculation_id_before": first_body["compute_queue"]["next_cursor_calculation_id_before"],
                },
            )

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        second_body = second_response.json()
        assert first_body["compute_recoveries"][0]["calculation_id"] == str(compute_ids[2])
        assert second_body["cursor_calculation_id_before"] == str(compute_ids[2])
        assert second_body["compute_recoveries"][0]["calculation_id"] == str(compute_ids[1])
    finally:
        compute_job_store.clear_all_records()
        lineage_metadata_store.clear_all_records()


def test_runtime_recoveries_reports_partial_queue_unavailability(mocker):
    mocker.patch(
        "app.services.runtime_recovery_service.compute_job_store.list_recent_recoveries",
        side_effect=RuntimeError("compute unavailable"),
    )
    mocker.patch(
        "app.services.runtime_recovery_service.lineage_metadata_store.list_recent_recoveries",
        return_value=type(
            "LineagePage",
            (),
            {
                "total_count": 0,
                "next_offset": None,
                "next_cursor_recovered_before": None,
                "next_cursor_calculation_id_before": None,
                "items": [],
            },
        )(),
    )

    with TestClient(app) as client:
        response = client.get("/integration/runtime-recoveries", params={"queue": "both", "limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["durable_metadata_store"]["status"] == "ready"
    assert body["compute_queue"] == {
        "status": "unavailable",
        "reason": COMPUTE_RECOVERY_READ_FAILED,
        "total_count": 0,
        "returned_count": 0,
        "next_offset": None,
        "next_cursor_recovered_before": None,
        "next_cursor_calculation_id_before": None,
    }
    assert body["lineage_queue"] == {
        "status": "available",
        "reason": None,
        "total_count": 0,
        "returned_count": 0,
        "next_offset": None,
        "next_cursor_recovered_before": None,
        "next_cursor_calculation_id_before": None,
    }
    assert body["compute_recoveries"] == []
    assert body["lineage_recoveries"] == []
