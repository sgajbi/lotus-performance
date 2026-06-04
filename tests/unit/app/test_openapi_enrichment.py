from app.openapi_enrichment import (
    _build_schema_example,
    _canonical_term,
    _ensure_request_body_example,
    _infer_description,
    _infer_example,
    _infer_schema_description,
    _semantic_id,
    _to_snake_case,
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
