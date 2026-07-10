from main import app


def _schema(name: str) -> dict:
    return app.openapi()["components"]["schemas"][name]


def test_runtime_recoveries_openapi_documents_operator_recovery_contract():
    operation = app.openapi()["paths"]["/integration/runtime-recoveries"]["get"]

    assert operation["summary"] == "List recent runtime recovery events"
    description = operation["description"]
    assert "runtime-status reports recovery activity" in description
    assert "deterministic seek pagination" in description
    assert "recovery-time windows" in description
    assert "direct execution, lineage, and async-result navigation links" in description
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RuntimeRecoveriesResponse"
    )

    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {
        "queue",
        "limit",
        "offset",
        "recovered_after",
        "recovered_before",
        "cursor_recovered_before",
        "cursor_calculation_id_before",
        "compute_analytics_type",
        "lineage_calculation_type",
        "calculation_id_contains",
    }
    assert parameters["queue"]["schema"]["enum"] == ["both", "compute", "lineage"]
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 100
    assert "deterministic seek pagination" in parameters["cursor_recovered_before"]["description"]
    calculation_filter = parameters["calculation_id_contains"]
    calculation_filter_schema = next(
        schema for schema in calculation_filter["schema"]["anyOf"] if schema.get("type") == "string"
    )
    assert calculation_filter_schema["minLength"] == 8
    assert calculation_filter_schema["maxLength"] == 36
    assert calculation_filter_schema["pattern"].startswith("^[0-9a-fA-F]{8}")
    assert "arbitrary substring search is not supported" in calculation_filter["description"]


def test_runtime_recoveries_response_schema_documents_all_output_families():
    for schema_name in [
        "RuntimeRecoveriesResponse",
        "RuntimeRecoveriesQueueStatusResponse",
        "app__models__runtime_recoveries__ComputeRecoveryEventResponse",
        "app__models__runtime_recoveries__LineageRecoveryEventResponse",
    ]:
        for field_name, field_schema in _schema(schema_name)["properties"].items():
            assert field_schema.get("description"), f"{schema_name}.{field_name} lacks a description"
            assert "example" in field_schema, f"{schema_name}.{field_name} lacks an example"

    response_properties = _schema("RuntimeRecoveriesResponse")["properties"]
    assert "durable metadata store" in response_properties["durable_metadata_store"]["description"]
    assert "Filtered compute recovery events" in response_properties["compute_recoveries"]["description"]
    assert "Filtered lineage recovery events" in response_properties["lineage_recoveries"]["description"]

    queue_properties = _schema("RuntimeRecoveriesQueueStatusResponse")["properties"]
    assert "compute_recovery_read_failed" in queue_properties["reason"]["description"]
    assert "lineage_recovery_read_failed" in queue_properties["reason"]["description"]
    assert "additional matching recovery events remain" in queue_properties["next_offset"]["description"]
    assert "deterministic seek pagination" in queue_properties["next_cursor_recovered_before"]["description"]

    compute_properties = _schema("app__models__runtime_recoveries__ComputeRecoveryEventResponse")["properties"]
    assert "Execution polling path" in compute_properties["execution_path"]["description"]
    assert "Async result path" in compute_properties["result_path"]["description"]

    lineage_properties = _schema("app__models__runtime_recoveries__LineageRecoveryEventResponse")["properties"]
    assert "Lineage inspection path" in lineage_properties["lineage_path"]["description"]
    assert "Attempt count" in lineage_properties["attempt_count"]["description"]
