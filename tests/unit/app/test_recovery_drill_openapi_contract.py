from main import app


def test_recovery_drill_history_openapi_documents_operator_evidence_contract():
    operation = app.openapi()["paths"]["/integration/recovery-drills"]["get"]

    assert operation["summary"] == "Get retained durable recovery-drill history"
    description = operation["description"]
    assert "latest recovery assurance" in description
    assert "retained evidence artifacts" in description
    assert "deterministic paging" in description
    assert "without shell access" in description
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RecoveryDrillHistoryResponse"
    )

    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {
        "limit",
        "offset",
        "operator_id",
        "backup_identifier",
        "status",
        "generated_after",
        "generated_before",
    }
    limit_integer_schema = parameters["limit"]["schema"]["anyOf"][0]
    assert limit_integer_schema["minimum"] == 1
    assert limit_integer_schema["maximum"] == 100
    assert "ISO-8601" in parameters["generated_after"]["description"]


def test_recovery_drill_run_openapi_documents_governed_execution_contract():
    operation = app.openapi()["paths"]["/integration/recovery-drills/run"]["post"]

    assert operation["summary"] == "Run a governed durable recovery drill"
    description = operation["description"]
    assert "backup or restore-set identifier" in description
    assert "idempotent replay" in description
    assert "cooldown" in description
    assert "stale-lease guards" in description
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RecoveryDrillRunRequest"
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RecoveryDrillRunResponse"
    )


def test_recovery_drill_schemas_document_all_request_and_output_fields():
    schemas = app.openapi()["components"]["schemas"]

    for schema_name in [
        "RecoveryDrillHistoryResponse",
        "RecoveryDrillHistoryEntryResponse",
        "RecoveryDrillRunRequest",
        "RecoveryDrillRunResponse",
    ]:
        for field_name, field_schema in schemas[schema_name]["properties"].items():
            assert field_schema.get("description"), f"{schema_name}.{field_name} lacks a description"
            assert "example" in field_schema, f"{schema_name}.{field_name} lacks an example"

    history_properties = schemas["RecoveryDrillHistoryResponse"]["properties"]
    assert "Total retained recovery-drill entries" in history_properties["total_entries"]["description"]
    assert "matching the applied filters" in history_properties["matched_entries"]["description"]
    assert "next page" in history_properties["next_offset"]["description"]

    run_properties = schemas["RecoveryDrillRunResponse"]["properties"]
    assert "Compute jobs processed" in run_properties["compute_job_processed_count"]["description"]
    assert "Lineage payloads processed" in run_properties["processed_payload_count"]["description"]
    assert "lineage artifact exists" in run_properties["materialized_artifact_exists"]["description"]
