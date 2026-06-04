from main import app
from scripts.openapi_completeness_inventory import (
    OpenApiCompletenessFinding,
    collect_openapi_completeness_findings,
    render_markdown,
)


def test_collect_openapi_completeness_findings_detects_missing_operation_metadata():
    schema = {
        "paths": {
            "/performance/example": {
                "get": {
                    "responses": {
                        "200": {"description": "OK"},
                    }
                }
            }
        }
    }

    rules = {finding.rule for finding in collect_openapi_completeness_findings(schema)}

    assert "MISSING_SUMMARY" in rules
    assert "MISSING_DESCRIPTION" in rules
    assert "MISSING_TAGS" in rules
    assert "MISSING_OPERATION_ID" in rules
    assert "MISSING_ERROR_RESPONSE" in rules


def test_collect_openapi_completeness_findings_detects_json_example_and_error_contract_gaps():
    schema = {
        "paths": {
            "/performance/example": {
                "post": {
                    "summary": "Example",
                    "description": "Example operation.",
                    "tags": ["Performance"],
                    "operationId": "example",
                    "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                    "responses": {
                        "202": {
                            "description": "Accepted",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                        "422": {"description": "Invalid", "content": {"application/json": {}}},
                    },
                }
            }
        }
    }

    findings = collect_openapi_completeness_findings(schema)
    rules = {finding.rule for finding in findings}

    assert "MISSING_REQUEST_JSON_EXAMPLE" in rules
    assert "MISSING_SUCCESS_JSON_EXAMPLE" in rules
    assert "ERROR_JSON_MISSING_SCHEMA" in rules
    assert "ERROR_JSON_MISSING_EXAMPLE" in rules
    assert "ERROR_RESPONSE_NOT_PROBLEM_DETAIL" in rules


def test_collect_openapi_completeness_findings_accepts_problem_detail_error_contracts():
    schema = {
        "paths": {
            "/performance/example": {
                "get": {
                    "summary": "Example",
                    "description": "Example operation.",
                    "tags": ["Performance"],
                    "operationId": "example",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"},
                                    "example": {"status": "ok"},
                                }
                            },
                        },
                        "404": {
                            "description": "Not found",
                            "content": {
                                "application/problem+json": {
                                    "schema": {"$ref": "#/components/schemas/ProblemDetail"},
                                    "example": {"title": "Not found"},
                                }
                            },
                        },
                    },
                }
            }
        }
    }

    assert collect_openapi_completeness_findings(schema) == []


def test_collect_openapi_completeness_findings_accepts_composed_error_contracts():
    schema = {
        "paths": {
            "/performance/example": {
                "post": {
                    "summary": "Example",
                    "description": "Example operation.",
                    "tags": ["Performance"],
                    "operationId": "example",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"},
                                    "example": {"status": "ok"},
                                }
                            },
                        },
                        "422": {
                            "description": "Invalid",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "oneOf": [
                                            {"$ref": "#/components/schemas/CompositeErrorResponse"},
                                            {"$ref": "#/components/schemas/HTTPValidationError"},
                                        ]
                                    },
                                    "example": {"detail": {"code": "NO_MEMBER_RETURN_FACTS"}},
                                }
                            },
                        },
                    },
                }
            }
        }
    }

    assert collect_openapi_completeness_findings(schema) == []


def test_lotus_performance_openapi_completeness_inventory_is_clean():
    findings = collect_openapi_completeness_findings(app.openapi())

    assert findings == []


def test_render_markdown_summarizes_openapi_findings():
    schema = {
        "paths": {
            "/performance/example": {
                "get": {
                    "summary": "Example",
                    "description": "Example operation.",
                    "tags": ["Performance"],
                    "operationId": "example",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
    }
    findings = [
        OpenApiCompletenessFinding(
            method="GET",
            path="/performance/example",
            rule="MISSING_ERROR_RESPONSE",
            description="missing error",
        ),
        OpenApiCompletenessFinding(
            method="GET",
            path="/performance/example",
            rule="MISSING_SUCCESS_JSON_EXAMPLE",
            description="missing example",
            response_code="200",
        ),
    ]

    output = render_markdown(schema, findings, limit=1)

    assert "| OpenAPI operations | 1 |" in output
    assert "| API completeness findings | 2 |" in output
    assert "| `MISSING_ERROR_RESPONSE` | 1 |" in output
    assert "| `GET /performance/example` | 2 |" in output
    assert "| 1 | `MISSING_ERROR_RESPONSE` | `GET /performance/example` | `` | missing error |" in output
    assert "missing example" not in output
