from __future__ import annotations

from main import app


def test_execution_openapi_documents_polling_contract() -> None:
    spec = app.openapi()
    operation = spec["paths"]["/performance/executions/{calculation_id}"]["get"]

    assert "async work accepted by TWR" in operation["description"]
    assert "endpoint-specific result route" in operation["description"]
    assert "404" in operation["responses"]
    not_found_json = operation["responses"]["404"]["content"]["application/json"]
    assert not_found_json["schema"]["$ref"].endswith("/ErrorDetailResponse")
    assert spec["components"]["schemas"]["ErrorDetailResponse"]["properties"]["detail"]["description"]
    assert not_found_json["example"] == {"detail": "Execution data not found for the given calculation_id."}
    assert operation["parameters"][0]["name"] == "calculation_id"
    assert "Durable calculation identifier" in operation["parameters"][0]["description"]


def test_execution_response_schema_documents_every_polling_field() -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    response_schema = schemas["ExecutionResponse"]
    stage_schema = schemas["ExecutionStageResponse"]
    snapshot_schema = schemas["UpstreamSnapshotResponse"]
    compute_schema = schemas["ComputeJobResponse"]
    result_schema = schemas["AsyncResultResponse"]

    for field_name in [
        "calculation_id",
        "analytics_type",
        "portfolio_id",
        "execution_mode",
        "status",
        "requested_window",
        "input_fingerprint",
        "calculation_hash",
        "error_message",
        "created_at_utc",
        "started_at_utc",
        "completed_at_utc",
        "stages",
        "upstream_snapshots",
        "compute_job",
        "async_result",
    ]:
        assert response_schema["properties"][field_name]["description"]

    for field_name in ["stage_name", "status", "started_at_utc", "completed_at_utc", "details", "error_message"]:
        assert stage_schema["properties"][field_name]["description"]

    for field_name in [
        "snapshot_id",
        "upstream_endpoint",
        "source_identifier",
        "as_of_date",
        "request_fingerprint",
        "response_fingerprint",
        "retrieval_status",
        "paging_metadata",
        "created_at_utc",
    ]:
        assert snapshot_schema["properties"][field_name]["description"]

    for field_name in [
        "job_status",
        "attempt_count",
        "max_attempts",
        "worker_id",
        "error_message",
        "error_type",
        "leased_at_utc",
        "lease_expires_at_utc",
        "last_error_at_utc",
        "created_at_utc",
        "started_at_utc",
        "completed_at_utc",
    ]:
        assert compute_schema["properties"][field_name]["description"]

    for field_name in ["result_status", "error_message", "error_type", "created_at_utc", "updated_at_utc"]:
        assert result_schema["properties"][field_name]["description"]

    assert response_schema["properties"]["analytics_type"]["examples"] == ["TWR"]
    assert compute_schema["properties"]["attempt_count"]["examples"] == [1]
    assert snapshot_schema["properties"]["upstream_endpoint"]["examples"] == ["portfolio_timeseries"]
