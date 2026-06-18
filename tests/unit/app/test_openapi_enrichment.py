from app.openapi_enrichment import (
    OPERATION_JSON_EXAMPLES,
    _application_json_content,
    _array_schema_example,
    _build_schema_example,
    _canonical_term,
    _composed_schema_example,
    _derived_schema_example,
    _documentable_operation,
    _ensure_model_schema_documentation,
    _ensure_operation_metadata,
    _ensure_operation_response_documentation,
    _ensure_property_description,
    _ensure_property_vocabulary_metadata,
    _ensure_request_body_example,
    _ensure_success_response_documentation,
    _enum_schema_example,
    _explicit_schema_example,
    _first_composed_schema_variant,
    _first_dict_schema_variant,
    _formatted_schema_example,
    _infer_description,
    _infer_example,
    _infer_schema_description,
    _iter_documentable_operations,
    _iter_schema_properties,
    _json_content_has_authored_example,
    _listed_schema_example,
    _named_schema_example,
    _named_schema_example_value,
    _non_ref_schema_example,
    _object_schema_example,
    _ref_schema_example,
    _request_body_example,
    _scalar_schema_example,
    _schema_hint_example,
    _semantic_id,
    _semantic_property_description,
    _semantic_string_example,
    _structural_schema_example,
    _temporal_string_example,
    _to_snake_case,
    _typed_schema_example,
    _validation_error_json_content,
    enrich_openapi_schema,
)


def test_to_snake_case_normalizes_camel_and_symbols():
    assert _to_snake_case("totalMarketValue") == "total_market_value"
    assert _to_snake_case("as-of.date") == "as_of_date"


def test_canonical_term_and_semantic_id_apply_legacy_mapping():
    legacy_client_term = "cif" + "_id"
    legacy_booking_center_term = "booking" + "_center"
    assert _canonical_term(legacy_client_term) == "client_id"
    assert _semantic_id(legacy_booking_center_term) == "lotus.booking_center_code"


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


def test_infer_example_helpers_preserve_schema_precedence():
    assert _enum_schema_example({"type": "string", "enum": ["NET", "GROSS"]}) == "NET"
    assert _enum_schema_example({"type": "string"}) is None
    assert _schema_hint_example("period", {"type": "string", "enum": ["YTD", "MTD"]}) == "YTD"
    assert _schema_hint_example("items", {"type": "array", "items": {"type": "string"}}) == ["example_items_item"]
    assert _schema_hint_example("as_of_date", {"type": "string", "format": "date"}) == "2026-02-27"
    assert _schema_hint_example("custom_field", {"type": "string"}) is None
    assert _typed_schema_example("portfolio_ids", {"type": "array", "items": {"type": "string"}}) == [
        "example_portfolio_ids_item"
    ]
    assert _typed_schema_example("metadata", {"type": "object"}) == {"key": "value"}
    assert _typed_schema_example("enabled", {"type": "boolean"}) is True
    assert _typed_schema_example("count", {"type": "integer"}) == 1
    assert _typed_schema_example("weight", {"type": "number"}) == 0.1234
    assert _typed_schema_example("as_of_date", {"type": "string"}) is None
    assert _formatted_schema_example({"type": "string", "format": "date"}) == "2026-02-27"
    assert _formatted_schema_example({"type": "string", "format": "date-time"}) == "2026-02-27T10:30:00Z"
    assert _formatted_schema_example({"type": "string"}) is None
    assert _semantic_string_example("base_currency") == "USD"
    assert _semantic_string_example("custom_value") == "example_custom_value"


def test_scalar_schema_example_returns_only_governed_scalar_defaults():
    assert _scalar_schema_example("boolean") is True
    assert _scalar_schema_example("integer") == 1
    assert _scalar_schema_example("number") == 0.1234
    assert _scalar_schema_example("string") is None


def test_temporal_string_example_preserves_date_before_time_precedence():
    assert _temporal_string_example("as_of_date") == "2026-02-27"
    assert _temporal_string_example("date_time") == "2026-02-27"
    assert _temporal_string_example("event_time") == "2026-02-27T10:30:00Z"
    assert _temporal_string_example("event_timestamp") == "2026-02-27T10:30:00Z"
    assert _temporal_string_example("base_currency") is None


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


def test_semantic_property_description_preserves_branch_outputs():
    assert _semantic_property_description("client_id", "client id", {"type": "string"}) == "Unique client identifier."
    assert _semantic_property_description("as_of_date", "as of date", {"format": "date"}) == (
        "Business date for as of date."
    )
    assert _semantic_property_description("generated_at", "generated at", {"format": "date-time"}) == (
        "Timestamp for generated at."
    )
    assert _semantic_property_description("base_currency", "base currency", {"type": "string"}) == (
        "ISO currency code for base currency."
    )
    assert _semantic_property_description("performance_return", "performance return", {"type": "number"}) == (
        "Performance metric value for performance return."
    )
    assert _semantic_property_description("net_value", "net value", {"type": "number"}) == (
        "Monetary value for net value."
    )
    assert _semantic_property_description("note", "note", {"type": "string"}) is None


def test_build_schema_example_resolves_refs_and_nested_content():
    components = {
        "schemas": {
            "Envelope": {
                "type": "object",
                "properties": {
                    "calculation_id": {"type": "string", "format": "uuid"},
                    "result": {"$ref": "#/components/schemas/Inner"},
                },
            },
            "Inner": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "complete"]},
                    "values": {"type": "array", "items": {"type": "integer"}},
                },
            },
        }
    }

    example = _build_schema_example({"$ref": "#/components/schemas/Envelope"}, components=components)

    assert example["calculation_id"] == "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"
    assert example["result"]["status"] == "pending"
    assert example["result"]["values"] == [1]


def test_ref_schema_example_resolves_refs_and_recursive_refs():
    components = {
        "schemas": {
            "Inner": {"type": "object", "properties": {"status": {"type": "string", "enum": ["complete"]}}},
            "Loop": {"type": "object", "properties": {"self": {"$ref": "#/components/schemas/Loop"}}},
        }
    }

    assert _ref_schema_example(
        {"$ref": "#/components/schemas/Inner"},
        components=components,
        seen_refs=set(),
    ) == {"status": "pending"}
    assert _ref_schema_example(
        {"$ref": "#/components/schemas/Loop"},
        components=components,
        seen_refs={"#/components/schemas/Loop"},
    ) == {"id": "recursive_ref"}
    assert _ref_schema_example({"type": "string"}, components=components, seen_refs=set()) is None


def test_schema_example_helpers_cover_explicit_composed_object_and_array_shapes():
    components = {"schemas": {}}

    assert _explicit_schema_example({"example": {"status": "ready"}}) == {"status": "ready"}
    assert _explicit_schema_example({"examples": [{"status": "pending"}]}) == {"status": "pending"}
    assert _explicit_schema_example({"examples": {"named": {"value": {"status": "complete"}}}}) == {
        "status": "complete"
    }
    assert (
        _composed_schema_example(
            {"oneOf": [{"type": "string", "enum": ["NET", "GROSS"]}]},
            components=components,
            seen_refs=set(),
            name_hint="metric_basis",
        )
        == "NET"
    )
    assert _object_schema_example(
        {"type": "object", "properties": {"portfolio_id": {"type": "string"}}},
        components=components,
        seen_refs=set(),
    ) == {"portfolio_id": "DEMO_DPM_EUR_001"}
    assert _object_schema_example({"type": "object"}, components=components, seen_refs=set()) == {"key": "value"}
    assert _array_schema_example(
        {"type": "array", "items": {"type": "integer"}},
        components=components,
        seen_refs=set(),
        name_hint="values",
    ) == [1]
    assert _array_schema_example(
        {"type": "array", "items": "not-a-dict"},
        components=components,
        seen_refs=set(),
        name_hint="values",
    ) == ["VALUE"]


def test_named_schema_example_extracts_first_named_value():
    assert _named_schema_example({"documented": {"value": {"status": "complete"}}}) == {"status": "complete"}
    assert _named_schema_example({"documented": {"summary": "missing value"}}) is None
    assert _named_schema_example([{"value": "not named"}]) is None


def test_named_schema_example_value_extracts_value_only_from_named_mapping():
    assert _named_schema_example_value({"value": {"status": "complete"}}) == {"status": "complete"}
    assert _named_schema_example_value({"summary": "missing value"}) is None
    assert _named_schema_example_value(["not named"]) is None


def test_first_composed_schema_variant_prefers_one_of_then_any_of_dict_variants():
    assert _first_composed_schema_variant({"oneOf": [{"type": "string"}]}) == {"type": "string"}
    assert _first_composed_schema_variant({"anyOf": [{"type": "integer"}]}) == {"type": "integer"}
    assert _first_composed_schema_variant({"oneOf": [], "anyOf": [{"type": "number"}]}) == {"type": "number"}
    assert _first_composed_schema_variant({"oneOf": ["not-a-dict"]}) is None
    assert _first_composed_schema_variant({"oneOf": "not-a-list"}) is None


def test_first_dict_schema_variant_accepts_only_non_empty_dict_variant_lists():
    assert _first_dict_schema_variant([{"type": "string"}]) == {"type": "string"}
    assert _first_dict_schema_variant([]) is None
    assert _first_dict_schema_variant(["not-a-dict"]) is None
    assert _first_dict_schema_variant("not-a-list") is None


def test_listed_schema_example_extracts_first_list_value():
    assert _listed_schema_example([{"status": "pending"}, {"status": "complete"}]) == {"status": "pending"}
    assert _listed_schema_example([]) is None
    assert _listed_schema_example({"named": {"value": "not a list"}}) is None


def test_structural_schema_example_routes_object_array_and_scalar_fallback():
    components = {"schemas": {}}

    assert _structural_schema_example(
        {"properties": {"portfolio_id": {"type": "string"}}},
        components=components,
        seen_refs=set(),
        name_hint="payload",
    ) == {"portfolio_id": "DEMO_DPM_EUR_001"}
    assert _structural_schema_example(
        {"type": "array", "items": {"type": "integer"}},
        components=components,
        seen_refs=set(),
        name_hint="values",
    ) == [1]
    assert (
        _structural_schema_example(
            {"type": "string"},
            components=components,
            seen_refs=set(),
            name_hint="status",
        )
        is None
    )


def test_derived_schema_example_prefers_composed_before_structural_examples():
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "oneOf": [{"type": "string", "enum": ["READY"]}],
    }
    assert _derived_schema_example(schema, components={}, seen_refs=set(), name_hint="status") == "pending"
    assert _derived_schema_example(
        {"type": "object"},
        components={},
        seen_refs=set(),
        name_hint="metadata",
    ) == {"key": "value"}


def test_ensure_request_body_example_uses_operation_override():
    request_body = {
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"portfolio_id": {"type": "string"}},
                }
            }
        }
    }

    _ensure_request_body_example(
        path="/performance/twr",
        request_body=request_body,
        components={"schemas": {}},
    )

    example = request_body["content"]["application/json"]["example"]
    assert example["input_mode"] == "stateless"
    assert example["portfolio_id"] == "DEMO_DPM_EUR_001"


def test_ensure_request_body_example_builds_schema_example_when_missing():
    request_body = {
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"portfolio_id": {"type": "string"}},
                }
            }
        }
    }

    _ensure_request_body_example(
        path="/custom/workflow",
        request_body=request_body,
        components={"schemas": {}},
    )

    assert request_body["content"]["application/json"]["example"] == {"portfolio_id": "DEMO_DPM_EUR_001"}


def test_ensure_request_body_example_preserves_existing_examples():
    request_body = {
        "content": {
            "application/json": {
                "schema": {"type": "object", "properties": {"portfolio_id": {"type": "string"}}},
                "examples": {"documented": {"value": {"portfolio_id": "EXISTING"}}},
            }
        }
    }

    _ensure_request_body_example(
        path="/custom/workflow",
        request_body=request_body,
        components={"schemas": {}},
    )

    assert "example" not in request_body["content"]["application/json"]
    assert request_body["content"]["application/json"]["examples"]["documented"]["value"]["portfolio_id"] == "EXISTING"


def test_ensure_request_body_example_ignores_malformed_content():
    request_body = {"content": {"application/json": "not-a-dict"}}

    _ensure_request_body_example(
        path="/custom/workflow",
        request_body=request_body,
        components={"schemas": {}},
    )

    assert request_body == {"content": {"application/json": "not-a-dict"}}


def test_request_body_example_preserves_override_authored_and_schema_precedence():
    override = _request_body_example(
        path="/performance/twr",
        json_content={"example": {"authored": True}, "schema": {"type": "string"}},
        components={},
    )
    assert override == OPERATION_JSON_EXAMPLES[("/performance/twr", "request")]
    assert override is not OPERATION_JSON_EXAMPLES[("/performance/twr", "request")]
    assert (
        _request_body_example(
            path="/unknown",
            json_content={"examples": {"documented": {"value": "existing"}}},
            components={},
        )
        is None
    )
    assert (
        _request_body_example(
            path="/unknown",
            json_content={"schema": "not-a-dict"},
            components={},
        )
        is None
    )
    assert (
        _request_body_example(
            path="/unknown",
            json_content={"schema": {"type": "integer"}},
            components={},
        )
        == 1
    )


def test_ensure_operation_response_documentation_adds_default_and_schema_example():
    responses = {
        "200": {
            "description": "ok",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"portfolio_id": {"type": "string"}},
                    }
                }
            },
        }
    }

    _ensure_operation_response_documentation(
        path="/custom/workflow",
        responses=responses,
        components={"schemas": {}},
    )

    assert responses["default"]["content"]["application/problem+json"]["example"]["status"] == 500
    assert responses["200"]["content"]["application/json"]["example"] == {"portfolio_id": "DEMO_DPM_EUR_001"}


def test_ensure_operation_response_documentation_uses_operation_override():
    responses = {
        "200": {
            "description": "ok",
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
        "422": {
            "description": "Validation Error",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/HTTPValidationError"}}},
        },
    }

    _ensure_operation_response_documentation(
        path="/health",
        responses=responses,
        components={"schemas": {"HTTPValidationError": {"type": "object"}}},
    )

    assert responses["200"]["content"]["application/json"]["example"] == {"status": "ok"}
    validation_example = responses["422"]["content"]["application/json"]["example"]
    assert validation_example["detail"][0]["loc"] == ["body", "portfolio_id"]


def test_validation_error_json_content_selects_undocumented_http_validation_schema():
    response = {
        "description": "Validation Error",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/HTTPValidationError"}}},
    }
    documented_response = {
        "description": "Validation Error",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/HTTPValidationError"},
                "example": {"detail": "already documented"},
            }
        },
    }

    json_content = _validation_error_json_content(response)

    assert json_content is response["content"]["application/json"]
    assert _validation_error_json_content(documented_response) is None
    assert _validation_error_json_content({"content": {"text/plain": {"schema": {"type": "string"}}}}) is None


def test_json_content_has_authored_example_detects_example_forms():
    assert _json_content_has_authored_example({"example": {"status": "ready"}}) is True
    assert _json_content_has_authored_example({"examples": {"ready": {"value": {"status": "ready"}}}}) is True
    assert _json_content_has_authored_example({"schema": {"type": "object"}}) is False


def test_application_json_content_selects_only_json_content_dicts():
    json_content = {"schema": {"type": "object"}}

    assert _application_json_content({"content": {"application/json": json_content}}) is json_content
    assert _application_json_content({"content": {"application/json": "not-a-dict"}}) is None
    assert _application_json_content({"content": "not-a-dict"}) is None
    assert _application_json_content("not-a-response") is None


def test_ensure_operation_response_documentation_rewrites_metrics_response():
    responses = {
        "200": {
            "description": "ok",
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    }

    _ensure_operation_response_documentation(
        path="/metrics",
        responses=responses,
        components={"schemas": {}},
    )

    content = responses["200"]["content"]
    assert "application/json" not in content
    assert content["text/plain"]["schema"]["description"] == "Prometheus exposition format payload."
    assert "lotus_performance_durable_queue_store_availability" in content["text/plain"]["example"]


def test_ensure_success_response_documentation_preserves_existing_json_examples():
    response = {
        "description": "ok",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"portfolio_id": {"type": "string"}},
                },
                "examples": {"documented": {"value": {"portfolio_id": "EXISTING"}}},
            }
        },
    }

    _ensure_success_response_documentation(
        path="/custom/workflow",
        response=response,
        components={"schemas": {}},
    )

    json_content = response["content"]["application/json"]
    assert "example" not in json_content
    assert json_content["examples"]["documented"]["value"] == {"portfolio_id": "EXISTING"}


def test_ensure_operation_metadata_assigns_governed_defaults_and_tags():
    health_operation = {}
    _ensure_operation_metadata(path="/health/ready", method="get", operation=health_operation)
    assert health_operation["summary"] == "GET /health/ready"
    assert health_operation["description"] == "GET operation for /health/ready in lotus-performance."
    assert health_operation["tags"] == ["Health"]

    metrics_operation = {"description": "Existing description"}
    _ensure_operation_metadata(path="/metrics", method="get", operation=metrics_operation)
    assert metrics_operation["tags"] == ["Monitoring"]
    assert "Prometheus metrics surface" in metrics_operation["description"]

    returns_series_operation = {}
    _ensure_operation_metadata(path="/returns-series/results", method="post", operation=returns_series_operation)
    assert returns_series_operation["tags"] == ["Returns Series"]

    workflow_operation = {"summary": "Existing summary", "tags": ["Existing"]}
    _ensure_operation_metadata(path="/returns-series/results", method="post", operation=workflow_operation)
    assert workflow_operation["summary"] == "Existing summary"
    assert workflow_operation["description"] == "POST operation for /returns-series/results in lotus-performance."
    assert workflow_operation["tags"] == ["Existing"]


def test_iter_documentable_operations_filters_malformed_paths_and_methods():
    operation = {"responses": {}}
    paths = {
        "/health": {"get": operation, "parameters": []},
        "/metrics": ["not-methods"],
        "/custom": {"trace": {}, "post": "not-operation"},
    }

    assert list(_iter_documentable_operations(paths)) == [("/health", "get", operation)]


def test_documentable_operation_normalizes_identity_and_filters_unsupported_shapes():
    operation = {"summary": "Health"}
    assert _documentable_operation(123, "GET", operation) == ("123", "GET", operation)
    assert _documentable_operation("/health", "parameters", operation) is None
    assert _documentable_operation("/health", "get", "not-a-dict") is None


def test_enrich_openapi_schema_fills_operation_schema_and_examples():
    schema = {
        "paths": {
            "/health": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/HealthResponse"}}
                            },
                        }
                    },
                }
            },
            "/performance/twr": {
                "post": {
                    "summary": "Compute TWR",
                    "requestBody": {
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/TwrRequest"}}}
                    },
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/TwrResponse"}}},
                        }
                    },
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
                "TwrRequest": {
                    "type": "object",
                    "properties": {
                        "portfolio_id": {"type": "string"},
                        "analyses": {"type": "array", "items": {"type": "string", "enum": ["YTD", "MTD"]}},
                    },
                },
                "TwrResponse": {
                    "type": "object",
                    "properties": {
                        "calculation_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "complete"]},
                    },
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
    default_error = health_get["responses"]["default"]["content"]["application/problem+json"]
    assert default_error["schema"]["$ref"] == "#/components/schemas/ProblemDetail"
    assert default_error["example"]["status"] == 500
    assert health_get["responses"]["200"]["content"]["application/json"]["example"]["status"] == "ok"

    perf_post = enriched["paths"]["/performance/twr"]["post"]
    assert perf_post["description"] == "POST operation for /performance/twr in lotus-performance."
    assert perf_post["tags"] == ["Performance"]
    assert perf_post["requestBody"]["content"]["application/json"]["example"]["portfolio_id"] == "DEMO_DPM_EUR_001"
    assert perf_post["responses"]["200"]["content"]["application/json"]["example"]["status"] == "pending"

    status_prop = enriched["components"]["schemas"]["HealthResponse"]["properties"]["status"]
    assert status_prop["description"]
    assert status_prop["example"] == "pending"
    assert status_prop["x-lotus-semantic-id"] == "lotus.status"
    assert status_prop["x-lotus-canonical-term"] == "status"

    request_id_prop = enriched["components"]["schemas"]["HealthResponse"]["properties"]["request_id"]
    assert request_id_prop["description"] == "Already set"
    assert request_id_prop["example"] == "REQ_1"

    preserved_schema = {
        "x-lotus-semantic-id": "lotus.custom",
        "x-lotus-canonical-term": "custom_term",
    }
    _ensure_property_vocabulary_metadata(prop_name="portfolio_id", prop_schema=preserved_schema)
    assert preserved_schema["x-lotus-semantic-id"] == "lotus.custom"
    assert preserved_schema["x-lotus-canonical-term"] == "custom_term"

    generated_schema: dict[str, object] = {}
    _ensure_property_vocabulary_metadata(prop_name="portfolio_id", prop_schema=generated_schema)
    assert generated_schema["x-lotus-semantic-id"] == "lotus.portfolio_id"
    assert generated_schema["x-lotus-canonical-term"] == "portfolio_id"

    other_count = enriched["components"]["schemas"]["Other"]["properties"]["count"]
    assert other_count["description"]
    assert other_count["example"] == 1

    twr_response_status = enriched["components"]["schemas"]["TwrResponse"]["properties"]["status"]
    assert twr_response_status["x-enum-descriptions"] == [
        "Allowed status value: pending.",
        "Allowed status value: complete.",
    ]

    nested_ref_prop = enriched["components"]["schemas"]["HealthResponse"]["properties"]["nested_ref"]
    assert nested_ref_prop["description"] == "health response field: nested ref."
    assert nested_ref_prop["example"] == {"count": 1}
    assert nested_ref_prop["x-lotus-semantic-id"] == "lotus.nested_ref"

    problem_schema = enriched["components"]["schemas"]["ProblemDetail"]
    assert problem_schema["description"].startswith("RFC 7807")
    assert problem_schema["properties"]["status"]["example"] == 500


def test_ensure_model_schema_documentation_preserves_existing_metadata_and_resolves_refs():
    components = {
        "schemas": {
            "Referenced": {
                "type": "object",
                "description": "Referenced schema description.",
                "properties": {"count": {"type": "integer"}},
            }
        }
    }
    model_schema = {
        "type": "object",
        "properties": {
            "request_id": {"type": "string", "description": "Already documented.", "example": "REQ_1"},
            "nested_ref": {"$ref": "#/components/schemas/Referenced"},
        },
    }

    _ensure_model_schema_documentation("Envelope", model_schema, components)

    assert model_schema["description"] == "envelope object."
    request_id = model_schema["properties"]["request_id"]
    assert request_id["description"] == "Already documented."
    assert request_id["example"] == "REQ_1"
    nested_ref = model_schema["properties"]["nested_ref"]
    assert nested_ref["description"] == "Referenced schema description."
    assert nested_ref["example"] == {"count": 1}
    assert nested_ref["x-lotus-semantic-id"] == "lotus.nested_ref"


def test_iter_schema_properties_yields_only_dict_properties():
    string_property = {"type": "string"}

    assert list(
        _iter_schema_properties(
            {
                "properties": {
                    "portfolio_id": string_property,
                    "ignored": "not-a-schema",
                    7: {"type": "integer"},
                }
            }
        )
    ) == [("portfolio_id", string_property), ("7", {"type": "integer"})]
    assert list(_iter_schema_properties({"properties": "not-a-dict"})) == []


def test_ensure_property_description_preserves_existing_and_uses_resolved_schema_description():
    documented_schema = {"description": "Already documented."}
    _ensure_property_description(
        model_name="Envelope",
        prop_name="request_id",
        prop_schema=documented_schema,
        prop_resolved={"description": "Resolved description."},
    )
    assert documented_schema["description"] == "Already documented."

    ref_schema: dict[str, object] = {}
    _ensure_property_description(
        model_name="Envelope",
        prop_name="nested_ref",
        prop_schema=ref_schema,
        prop_resolved={"description": "Referenced schema description."},
    )
    assert ref_schema["description"] == "Referenced schema description."


def test_enrich_openapi_schema_adds_fastapi_validation_error_examples():
    schema = {
        "paths": {
            "/performance/example": {
                "post": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                        "422": {
                            "description": "Validation Error",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/HTTPValidationError"}}
                            },
                        },
                    },
                }
            },
            "/performance/domain-error": {
                "post": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                        "422": {
                            "description": "Domain error",
                            "content": {"application/json": {"example": {"detail": "already documented"}}},
                        },
                    },
                }
            },
        },
        "components": {"schemas": {"HTTPValidationError": {"type": "object"}}},
    }

    enriched = enrich_openapi_schema(schema)

    validation_json = enriched["paths"]["/performance/example"]["post"]["responses"]["422"]["content"][
        "application/json"
    ]
    domain_json = enriched["paths"]["/performance/domain-error"]["post"]["responses"]["422"]["content"][
        "application/json"
    ]
    assert validation_json["example"]["detail"][0]["loc"] == ["body", "portfolio_id"]
    assert validation_json["example"]["detail"][0]["msg"] == "Field required"
    assert domain_json["example"] == {"detail": "already documented"}


def test_enrich_openapi_schema_uses_contract_valid_twr_request_example():
    schema = {
        "paths": {
            "/performance/twr": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "input_mode": {"type": "string"},
                                        "portfolio_id": {"type": "string"},
                                        "performance_start_date": {"type": "string", "format": "date"},
                                        "analyses": {"type": "array", "items": {"type": "object"}},
                                        "stateless_input": {"type": "object"},
                                        "stateful_input": {"type": "object"},
                                        "valuation_points": {"type": "array", "items": {"type": "object"}},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "ok", "content": {"application/json": {"schema": {"type": "object"}}}}
                    },
                }
            }
        },
        "components": {"schemas": {}},
    }

    enriched = enrich_openapi_schema(schema)
    example = enriched["paths"]["/performance/twr"]["post"]["requestBody"]["content"]["application/json"]["example"]

    assert example["input_mode"] == "stateless"
    assert "stateless_input" in example
    assert "stateful_input" not in example
    assert "valuation_points" not in example


def test_infer_example_and_description_cover_fallback_branches():
    assert _infer_example("items", {"type": "array", "items": "not-a-dict"}) == ["VALUE"]
    assert _infer_example("settlement_date", {"type": "string", "format": "date"}) == "2026-02-27"
    assert _infer_example("event_timestamp", {"type": "string", "format": "date-time"}) == "2026-02-27T10:30:00Z"
    assert _infer_example("event_time", {"type": "string"}) == "2026-02-27T10:30:00Z"
    assert _infer_example("trade_date_label", {"type": "string"}) == "2026-02-27"
    assert _infer_example("quote_currency", {"type": "string"}) == "USD"
    assert _infer_example("custom_field", {"type": "string"}) == "example_custom_field"

    assert _infer_description("Response", "level", {"type": "string"}) == "response field: level."
    assert _infer_schema_description("GenericThing", {"type": "string"}) == "generic thing schema."


def test_build_schema_example_covers_recursive_examples_and_union_forms():
    components = {
        "schemas": {
            "Loop": {
                "type": "object",
                "properties": {
                    "self": {"$ref": "#/components/schemas/Loop"},
                },
            }
        }
    }

    assert _build_schema_example({"$ref": "#/components/schemas/Loop"}, components=components) == {
        "self": {"id": "recursive_ref"}
    }
    assert _build_schema_example({"examples": ["alpha", "beta"]}, components=components) == "alpha"
    assert _build_schema_example(
        {"examples": {"named": {"value": {"status": "pending"}}}},
        components=components,
    ) == {"status": "pending"}
    assert (
        _build_schema_example(
            {"oneOf": [{"type": "string", "enum": ["NET", "GROSS"]}]},
            components=components,
        )
        == "NET"
    )
    assert (
        _build_schema_example(
            {"anyOf": [{"type": "integer"}, {"type": "string"}]},
            components=components,
        )
        == 1
    )
    assert _build_schema_example({"type": "object"}, components=components) == {"key": "value"}
    assert _build_schema_example({"type": "array", "items": "not-a-dict"}, components=components) == ["VALUE"]


def test_non_ref_schema_example_routes_explicit_derived_and_inferred_examples():
    components = {"schemas": {}}

    assert _non_ref_schema_example(
        {"example": {"status": "ready"}},
        components=components,
        seen_refs=set(),
        name_hint="status",
    ) == {"status": "ready"}
    assert (
        _non_ref_schema_example(
            {"oneOf": [{"type": "string", "enum": ["NET", "GROSS"]}]},
            components=components,
            seen_refs=set(),
            name_hint="metric_basis",
        )
        == "NET"
    )
    assert (
        _non_ref_schema_example(
            {"type": "string"},
            components=components,
            seen_refs=set(),
            name_hint="custom_field",
        )
        == "example_custom_field"
    )


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


def test_enrich_openapi_schema_covers_metrics_tags_and_model_level_enum_metadata():
    schema = {
        "paths": {
            "/metrics": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "Prometheus text format",
                            "content": {"text/plain": {"schema": {"type": "string"}}},
                        }
                    },
                }
            },
            "/custom": {
                "trace": {"summary": "ignored"},
                "post": {
                    "responses": {
                        "204": {
                            "description": "No content",
                        }
                    },
                },
            },
        },
        "components": {
            "schemas": {
                "StatusEnum": {
                    "type": "string",
                    "enum": ["pending", "complete"],
                },
                "BrokenProperties": {
                    "type": "object",
                    "properties": {
                        "valid": {"type": "string"},
                        "broken": "not-a-dict",
                    },
                },
                "IgnoredSchema": "not-a-dict",
            }
        },
    }

    enriched = enrich_openapi_schema(schema)

    assert enriched["paths"]["/metrics"]["get"]["tags"] == ["Monitoring"]
    assert "default" in enriched["paths"]["/metrics"]["get"]["responses"]
    assert (
        "lotus_performance_durable_queue_store_availability"
        in enriched["paths"]["/metrics"]["get"]["responses"]["200"]["content"]["text/plain"]["example"]
    )
    assert enriched["paths"]["/custom"]["trace"] == {"summary": "ignored"}
    assert "default" in enriched["paths"]["/custom"]["post"]["responses"]
    assert enriched["components"]["schemas"]["StatusEnum"]["x-enum-descriptions"] == [
        "Allowed status enum value: pending.",
        "Allowed status enum value: complete.",
    ]
    assert enriched["components"]["schemas"]["BrokenProperties"]["properties"]["valid"]["example"] == "example_valid"
    assert enriched["components"]["schemas"]["BrokenProperties"]["properties"]["broken"] == "not-a-dict"


def test_enrich_openapi_schema_handles_malformed_root_sections_and_response_content():
    schema_with_bad_roots = {
        "paths": [],
        "components": [],
    }

    assert enrich_openapi_schema(schema_with_bad_roots) == schema_with_bad_roots

    schema_with_bad_method_and_content = {
        "paths": {
            "/broken": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": "not-a-dict",
                        }
                    },
                },
                "parameters": {},
            }
        },
        "components": {"schemas": {}},
    }

    enriched = enrich_openapi_schema(schema_with_bad_method_and_content)

    assert enriched["paths"]["/broken"]["parameters"] == {}
    assert "default" in enriched["paths"]["/broken"]["get"]["responses"]

    schema_with_non_dict_methods = {
        "paths": {
            "/bad": [],
        },
        "components": {"schemas": "not-a-dict"},
    }

    assert enrich_openapi_schema(schema_with_non_dict_methods) == schema_with_non_dict_methods
