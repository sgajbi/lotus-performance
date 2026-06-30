from main import app


def test_runtime_work_items_openapi_documents_operator_drilldown_contract():
    schema = app.openapi()
    operation = schema["paths"]["/integration/runtime-work-items"]["get"]

    assert operation["summary"] == "List filtered runtime work items"
    description = operation["description"]
    assert "runtime queue pressure" in description
    assert "active, failed, or reclaimable backlog" in description
    assert "analytics-family filtering" in description
    assert "direct execution, lineage, and async-result navigation links" in description
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RuntimeWorkItemsResponse"
    )

    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {
        "queue",
        "status",
        "limit",
        "offset",
        "min_age_seconds",
        "compute_analytics_type",
        "lineage_calculation_type",
        "calculation_id_contains",
    }
    assert parameters["queue"]["schema"]["enum"] == ["both", "compute", "lineage"]
    assert parameters["status"]["schema"]["enum"] == ["active", "failed", "all", "reclaimable"]
    assert "reclaimable" in parameters["status"]["description"]
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 100


def test_runtime_work_items_response_schema_documents_all_output_families():
    schemas = app.openapi()["components"]["schemas"]

    for schema_name in [
        "RuntimeWorkItemsResponse",
        "RuntimeWorkItemQueueStatusResponse",
        "ComputeRuntimeWorkItemResponse",
        "LineageRuntimeWorkItemResponse",
    ]:
        for field_name, field_schema in schemas[schema_name]["properties"].items():
            assert field_schema.get("description"), f"{schema_name}.{field_name} lacks a description"
            assert "example" in field_schema, f"{schema_name}.{field_name} lacks an example"

    response_properties = schemas["RuntimeWorkItemsResponse"]["properties"]
    assert "durable metadata store" in response_properties["durable_metadata_store"]["description"]
    assert "Filtered compute work items" in response_properties["compute_items"]["description"]
    assert "Filtered lineage work items" in response_properties["lineage_items"]["description"]

    queue_properties = schemas["RuntimeWorkItemQueueStatusResponse"]["properties"]
    assert "compute_work_item_read_failed" in queue_properties["reason"]["description"]
    assert "lineage_work_item_read_failed" in queue_properties["reason"]["description"]
    assert "additional matching work items remain" in queue_properties["next_offset"]["description"]

    compute_properties = schemas["ComputeRuntimeWorkItemResponse"]["properties"]
    assert "Execution polling path" in compute_properties["execution_path"]["description"]
    assert "Async result path" in compute_properties["result_path"]["description"]

    lineage_properties = schemas["LineageRuntimeWorkItemResponse"]["properties"]
    assert "Lineage inspection path" in lineage_properties["lineage_path"]["description"]
    assert "materialization attempts" in lineage_properties["attempt_count"]["description"]
