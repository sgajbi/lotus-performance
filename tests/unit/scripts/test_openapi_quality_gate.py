from scripts.openapi_quality_gate import evaluate_schema


def test_evaluate_schema_accepts_clean_openapi_contract():
    schema = {
        "paths": {
            "/performance/returns": {
                "get": {
                    "summary": "Get benchmark returns",
                    "description": "Returns benchmark attribution details.",
                    "tags": ["Performance"],
                    "operationId": "getReturns",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ReturnsSeries"},
                                    "example": {"value": 1.23},
                                }
                            },
                        },
                        "404": {
                            "description": "Missing returns",
                            "content": {
                                "application/problem+json": {
                                    "schema": {"$ref": "#/components/schemas/ProblemDetail"},
                                    "example": {"title": "Not found"},
                                }
                            },
                        },
                    },
                },
            }
        },
        "components": {
            "schemas": {
                "ReturnsSeries": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Return series status.",
                            "example": "ok",
                            "x-lotus-semantic-id": "lotus.performance.returns.status",
                            "x-lotus-canonical-term": "return-status",
                        }
                    },
                },
                "ProblemDetail": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Human-readable summary.",
                            "example": "Bad request",
                            "x-lotus-semantic-id": "lotus.title",
                            "x-lotus-canonical-term": "title",
                        }
                    },
                },
            }
        },
    }

    assert evaluate_schema(schema, service_name="lotus-performance") == []


def test_evaluate_schema_flags_endpoint_metadata_gaps():
    schema = {
        "paths": {
            "/performance/returns": {
                "post": {
                    "operationId": "createReturns",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ReturnsSeries"},
                                }
                            },
                        },
                        "409": {"description": "Conflict"},
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "ReturnsSeries": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                }
            }
        },
    }

    errors = evaluate_schema(schema, service_name="lotus-performance")

    assert any("missing summary" in item for item in errors)
    assert any("missing description" in item for item in errors)
    assert any("missing tags" in item for item in errors)
    assert any("missing endpoint documentation/response contract" in item for item in errors)
    assert any("200 application/json example" in item for item in errors)


def test_evaluate_schema_flags_schema_metadata_gaps():
    schema = {
        "paths": {
            "/performance/returns": {
                "get": {
                    "summary": "Get benchmark returns",
                    "description": "Returns benchmark attribution details.",
                    "tags": ["Performance"],
                    "operationId": "getReturns",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ReturnsSeries"},
                                    "example": {"value": 1.23},
                                }
                            },
                        },
                        "400": {
                            "description": "Bad input",
                            "content": {
                                "application/problem+json": {
                                    "schema": {"$ref": "#/components/schemas/ProblemDetail"},
                                    "example": {"title": "Bad input"},
                                }
                            },
                        },
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "ReturnsSeries": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "status_ref": {"$ref": "#/components/schemas/Nested"},
                    },
                },
                "ProblemDetail": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Human-readable summary.",
                            "example": "Bad request",
                            "x-lotus-semantic-id": "lotus.title",
                            "x-lotus-canonical-term": "title",
                        }
                    },
                },
                "Nested": {"type": "object", "properties": {"x": {"type": "integer"}}},
            }
        },
    }

    errors = evaluate_schema(schema, service_name="lotus-performance")

    assert any("missing schema field metadata" in item for item in errors)
    assert any("ReturnsSeries.status: missing description" in item for item in errors)
    assert any("ReturnsSeries.status: missing example" in item for item in errors)
    assert any("ReturnsSeries.status: missing x-lotus-semantic-id" in item for item in errors)
    assert any("ReturnsSeries.status: missing x-lotus-canonical-term" in item for item in errors)
    assert not any("status_ref" in item for item in errors)


def test_evaluate_schema_reports_duplicate_operation_ids():
    schema = {
        "paths": {
            "/performance/returns": {
                "get": {
                    "summary": "Get returns",
                    "description": "Get returns.",
                    "tags": ["Performance"],
                    "operationId": "returns.id",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ReturnsSeries"},
                                    "example": {"value": 1.23},
                                }
                            },
                        },
                        "400": {
                            "description": "Bad",
                            "content": {
                                "application/problem+json": {
                                    "schema": {"$ref": "#/components/schemas/ProblemDetail"},
                                    "example": {"title": "Bad"},
                                }
                            },
                        },
                    },
                }
            },
            "/performance/returns/{id}": {
                "get": {
                    "summary": "Get returns by id",
                    "description": "Get returns by id.",
                    "tags": ["Performance"],
                    "operationId": "returns.id",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ReturnsSeries"},
                                    "example": {"value": 2.34},
                                }
                            },
                        },
                        "400": {
                            "description": "Bad",
                            "content": {
                                "application/problem+json": {
                                    "schema": {"$ref": "#/components/schemas/ProblemDetail"},
                                    "example": {"title": "Bad"},
                                }
                            },
                        },
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "ReturnsSeries": {"type": "object", "properties": {"status": {"type": "string"}}},
                "ProblemDetail": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Human-readable summary.",
                            "example": "Bad request",
                            "x-lotus-semantic-id": "lotus.title",
                            "x-lotus-canonical-term": "title",
                        }
                    },
                },
            }
        },
    }

    errors = evaluate_schema(schema, service_name="lotus-performance")

    assert "OpenAPI quality gate (lotus-performance): duplicate operationId values" in errors
    assert "  - returns.id" in errors
