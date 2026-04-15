from main import app


def test_root_openapi_documents_service_entry_contract():
    operation = app.openapi()["paths"]["/"]["get"]

    assert operation["summary"] == "Service entry"
    assert "points callers to `/docs`" in operation["description"]
    assert operation["responses"]["200"]["content"]["application/json"]["example"]["message"].startswith(
        "Welcome to the Portfolio Performance Analytics API"
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/RootResponse")


def test_health_openapi_documents_operational_contracts():
    schema = app.openapi()

    health_operation = schema["paths"]["/health"]["get"]
    assert "lightweight reachability probe" in health_operation["description"]
    assert health_operation["responses"]["200"]["content"]["application/json"]["example"] == {"status": "ok"}

    live_operation = schema["paths"]["/health/live"]["get"]
    assert "process is running" in live_operation["description"]
    assert live_operation["responses"]["200"]["content"]["application/json"]["example"] == {"status": "live"}

    ready_operation = schema["paths"]["/health/ready"]["get"]
    assert "durable metadata and lineage storage dependencies are usable" in ready_operation["description"]
    assert ready_operation["responses"]["200"]["content"]["application/json"]["example"] == {"status": "ready"}

    health_schema = schema["components"]["schemas"]["HealthStatusResponse"]
    for field_name, field_schema in health_schema["properties"].items():
        assert field_schema.get("description"), f"HealthStatusResponse.{field_name} lacks a description"
        assert "example" in field_schema, f"HealthStatusResponse.{field_name} lacks an example"


def test_metrics_openapi_documents_prometheus_surface():
    operation = app.openapi()["paths"]["/metrics"]["get"]

    assert operation["summary"] == "Metrics"
    assert "Prometheus metrics surface" in operation["description"]
    response_content = operation["responses"]["200"]["content"]
    assert "text/plain" in response_content
    assert response_content["text/plain"]["schema"]["type"] == "string"
    assert "lotus_performance_durable_queue_store_availability" in response_content["text/plain"]["example"]
