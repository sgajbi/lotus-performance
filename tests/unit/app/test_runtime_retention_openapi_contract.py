from main import app


def test_runtime_retention_history_openapi_documents_operator_evidence_contract():
    operation = app.openapi()["paths"]["/integration/runtime-retention-cleanups"]["get"]

    assert operation["summary"] == "Get retained runtime-retention cleanup history"
    description = operation["description"]
    assert "latest cleanup assurance" in description
    assert "deterministic paging" in description
    assert "prunable counts" in description
    assert "without shell access" in description

    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {
        "limit",
        "offset",
        "operator_id",
        "trigger_mode",
        "job_id",
        "cleanup_mode",
        "status",
        "generated_after",
        "generated_before",
    }
    limit_integer_schema = parameters["limit"]["schema"]["anyOf"][0]
    assert limit_integer_schema["minimum"] == 1
    assert limit_integer_schema["maximum"] == 100
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RuntimeRetentionHistoryResponse"
    )


def test_runtime_retention_run_openapi_documents_governed_execution_contract():
    operation = app.openapi()["paths"]["/integration/runtime-retention-cleanups/run"]["post"]

    assert operation["summary"] == "Run a governed runtime-retention cleanup preview or apply action"
    description = operation["description"]
    assert "preview-before-apply" in description
    assert "idempotent replay" in description
    assert "cooldown" in description
    assert "stale-lease guards" in description
    assert "lineage-artifact counts" in description
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RuntimeRetentionCleanupRunRequest"
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RuntimeRetentionCleanupRunResponse"
    )


def test_runtime_retention_schemas_document_all_request_and_output_fields():
    schemas = app.openapi()["components"]["schemas"]

    for schema_name in [
        "RuntimeRetentionHistoryResponse",
        "RuntimeRetentionHistoryEntryResponse",
        "RuntimeRetentionCleanupRunRequest",
        "RuntimeRetentionCleanupRunResponse",
    ]:
        for field_name, field_schema in schemas[schema_name]["properties"].items():
            assert field_schema.get("description"), f"{schema_name}.{field_name} lacks a description"
            assert "example" in field_schema, f"{schema_name}.{field_name} lacks an example"

    history_properties = schemas["RuntimeRetentionHistoryResponse"]["properties"]
    assert "Total retained runtime-retention entries" in history_properties["total_entries"]["description"]
    assert "matching the applied filters" in history_properties["matched_entries"]["description"]

    run_properties = schemas["RuntimeRetentionCleanupRunResponse"]["properties"]
    assert "Terminal execution records" in run_properties["prunable_execution_count"]["description"]
    assert "Async results selected" in run_properties["prunable_async_result_count"]["description"]
    assert "Lineage artifact directories" in run_properties["prunable_lineage_artifact_count"]["description"]

    request_properties = schemas["RuntimeRetentionCleanupRunRequest"]["properties"]
    job_id_schema = request_properties["job_id"]["anyOf"][0]
    assert job_id_schema["minLength"] == 1
    assert job_id_schema["pattern"] == r".*\S.*"
