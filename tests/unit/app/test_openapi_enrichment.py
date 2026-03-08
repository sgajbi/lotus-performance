from app.openapi_enrichment import (
    _infer_description,
    _infer_example,
    _to_snake_case,
    enrich_openapi_schema,
)


def test_to_snake_case_normalizes_camel_and_symbols():
    assert _to_snake_case("totalMarketValue") == "total_market_value"
    assert _to_snake_case("as-of.date") == "as_of_date"


def test_infer_example_prefers_named_examples_and_schema_hints():
    assert _infer_example("portfolio_id", {"type": "string"}) == "DEMO_DPM_EUR_001"
    assert _infer_example("period", {"enum": ["YTD", "MTD"]}) == "YTD"
    assert _infer_example("as_of_date", {"type": "string", "format": "date"}) == "2026-02-27"
    assert _infer_example("generated_at", {"type": "string", "format": "date-time"}) == "2026-02-27T10:30:00Z"
    assert _infer_example("is_ready", {"type": "boolean"}) is True
    assert _infer_example("count", {"type": "integer"}) == 1
    assert _infer_example("value", {"type": "number"}) == 0.1234
    assert _infer_example("items", {"type": "array", "items": {"type": "string"}}) == ["example_items_item"]
    assert _infer_example("meta", {"type": "object"}) == {"key": "value"}
    assert _infer_example("custom_id", {"type": "string"}) == "CUSTOM_001"


def test_infer_description_uses_semantic_branches():
    assert _infer_description("Response", "client_id", {"type": "string"}) == "Unique client identifier."
    assert _infer_description("Response", "as_of_date", {"format": "date"}) == "Business date for as of date."
    assert _infer_description("Response", "generated_at", {"format": "date-time"}) == "Timestamp for generated at."
    assert _infer_description("Response", "base_currency", {"type": "string"}) == "ISO currency code for base currency."
    assert (
        _infer_description("Response", "performance_return", {"type": "number"})
        == "Performance metric value for performance return."
    )
    assert _infer_description("Response", "net_value", {"type": "number"}) == "Monetary value for net value."
    assert _infer_description("ResponseModel", "note", {"type": "string"}) == "response model field: note."


def test_enrich_openapi_schema_fills_operation_and_schema_gaps():
    schema = {
        "paths": {
            "/health": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/metrics": {
                "get": {
                    "summary": "Metrics",
                    "description": "Metrics endpoint",
                    "tags": ["Monitoring"],
                    "responses": {"200": {"description": "ok"}, "500": {"description": "error"}},
                }
            },
            "/performance/twr": {
                "post": {
                    "summary": "Compute TWR",
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
        "components": {
            "schemas": {
                "HealthResponse": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "request_id": {"type": "string", "description": "Already set", "example": "REQ_1"},
                        "nested_ref": {"$ref": "#/components/schemas/Other"},
                    },
                },
                "Other": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                },
            }
        },
    }

    enriched = enrich_openapi_schema(schema)

    health_get = enriched["paths"]["/health"]["get"]
    assert health_get["summary"] == "GET /health"
    assert health_get["description"] == "GET operation for /health in lotus-performance."
    assert health_get["tags"] == ["Health"]
    assert "default" in health_get["responses"]

    perf_post = enriched["paths"]["/performance/twr"]["post"]
    assert perf_post["description"] == "POST operation for /performance/twr in lotus-performance."
    assert perf_post["tags"] == ["Performance"]
    assert "default" in perf_post["responses"]

    metrics_get = enriched["paths"]["/metrics"]["get"]
    assert metrics_get["summary"] == "Metrics"
    assert metrics_get["description"] == "Metrics endpoint"
    assert metrics_get["tags"] == ["Monitoring"]
    assert "default" not in metrics_get["responses"]

    status_prop = enriched["components"]["schemas"]["HealthResponse"]["properties"]["status"]
    assert status_prop["description"]
    assert status_prop["example"] == "ok"

    request_id_prop = enriched["components"]["schemas"]["HealthResponse"]["properties"]["request_id"]
    assert request_id_prop["description"] == "Already set"
    assert request_id_prop["example"] == "REQ_1"

    other_count = enriched["components"]["schemas"]["Other"]["properties"]["count"]
    assert other_count["description"]
    assert other_count["example"] == 1


def test_infer_example_and_description_cover_fallback_branches():
    assert _infer_example("items", {"type": "array", "items": "not-a-dict"}) == ["VALUE"]
    assert _infer_example("event_time", {"type": "string"}) == "2026-02-27T10:30:00Z"
    assert _infer_example("trade_date_label", {"type": "string"}) == "2026-02-27"
    assert _infer_example("quote_currency", {"type": "string"}) == "USD"
    assert _infer_example("custom_field", {"type": "string"}) == "example_custom_field"

    assert _infer_description("Response", "level", {"type": "string"}) == "response field: level."


def test_enrich_openapi_schema_ignores_non_object_sections_and_non_http_methods():
    schema = {
        "paths": {
            "/health": {"parameters": ["not-an-operation"]},
            "/custom": {"post": "invalid"},
        },
        "components": {
            "schemas": {
                "Broken": {"type": "object", "properties": "invalid"},
                "Ignored": "not-a-dict",
            }
        },
    }

    enriched = enrich_openapi_schema(schema)

    assert enriched["paths"]["/health"]["parameters"] == ["not-an-operation"]
    assert enriched["paths"]["/custom"]["post"] == "invalid"
