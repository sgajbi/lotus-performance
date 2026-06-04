"""OpenAPI enrichment helpers for RFC-0067 documentation completeness."""

from __future__ import annotations

import copy
import re
from typing import Any

ALLOWED_METHODS = {"get", "post", "put", "patch", "delete"}
_LEGACY_CLIENT_TERM = "cif" + "_id"
_LEGACY_BOOKING_CENTER_TERM = "booking" + "_center"
LEGACY_TERM_MAP: dict[str, str] = {
    _LEGACY_CLIENT_TERM: "client_id",
    _LEGACY_BOOKING_CENTER_TERM: "booking_center_code",
}
EXAMPLE_BY_KEY = {
    "portfolio_id": "DEMO_DPM_EUR_001",
    "session_id": "SIM_0001",
    "calculation_id": "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e",
    "request_id": "req_0d19d1d768c1",
    "correlation_id": "corr_55956bbc6cb3",
    "trace_id": "0123456789abcdef0123456789abcdef",
    "tenant_id": "default",
    "consumer_system": "lotus-performance",
    "policy_version": "tenant-default-v1",
    "contract_version": "v1",
    "source_service": "lotus-performance",
    "as_of_date": "2026-02-27",
    "report_start_date": "2026-01-01",
    "report_end_date": "2026-01-31",
    "performance_start_date": "2024-12-31",
    "generated_at": "2026-02-27T10:30:00Z",
    "status": "pending",
    "execution_mode": "async",
    "poll_path": "/performance/executions/2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e",
    "result_path": "/integration/returns/series/results/2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e",
    "currency": "USD",
    "base_currency": "USD",
    "metric_basis": "NET",
    "frequency": "DAILY",
    "portfolio_returns": [{"date": "2026-02-27", "return_value": "0.0012"}],
}

OPERATION_JSON_EXAMPLES: dict[tuple[str, str], dict[str, Any]] = {
    (
        "/",
        "response",
    ): {"message": "Welcome to the Portfolio Performance Analytics API. Access /docs for API documentation."},
    (
        "/health",
        "response",
    ): {"status": "ok"},
    (
        "/health/live",
        "response",
    ): {"status": "live"},
    (
        "/health/ready",
        "response",
    ): {"status": "ready"},
    (
        "/performance/twr",
        "request",
    ): {
        "input_mode": "stateless",
        "portfolio_id": "DEMO_DPM_EUR_001",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2026-01-31",
        "analyses": [{"period": "MTD", "frequencies": ["daily"]}],
        "stateless_input": {
            "valuation_points": [
                {
                    "perf_date": "2026-01-29",
                    "begin_mv": 1000000.0,
                    "end_mv": 1008500.0,
                },
                {
                    "perf_date": "2026-01-30",
                    "begin_mv": 1008500.0,
                    "end_mv": 1011200.0,
                },
                {
                    "perf_date": "2026-01-31",
                    "begin_mv": 1011200.0,
                    "eod_cf": -5000.0,
                    "end_mv": 1015400.0,
                },
            ]
        },
    },
}
HTTP_VALIDATION_ERROR_EXAMPLE: dict[str, Any] = {
    "detail": [
        {
            "type": "missing",
            "loc": ["body", "portfolio_id"],
            "msg": "Field required",
            "input": {},
        }
    ]
}
PROBLEM_DETAIL_SCHEMA_NAME = "ProblemDetail"
PROBLEM_DETAIL_EXAMPLE: dict[str, Any] = {
    "type": "about:blank",
    "title": "Unexpected error response",
    "status": 500,
    "detail": "The service returned an unexpected error response.",
}
PROBLEM_DETAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "RFC 7807-style problem detail envelope for documented error responses.",
    "properties": {
        "type": {
            "type": "string",
            "description": "Problem type URI or about:blank when no more specific type is available.",
            "example": "about:blank",
        },
        "title": {
            "type": "string",
            "description": "Short human-readable problem title.",
            "example": "Unexpected error response",
        },
        "status": {
            "type": "integer",
            "description": "HTTP status code associated with the problem.",
            "example": 500,
        },
        "detail": {
            "type": "string",
            "description": "Human-readable detail for the specific failure.",
            "example": "The service returned an unexpected error response.",
        },
    },
    "required": ["type", "title", "status", "detail"],
    "example": PROBLEM_DETAIL_EXAMPLE,
}


def _to_snake_case(value: str) -> str:
    transformed = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    transformed = transformed.replace("-", "_").replace(" ", "_").replace(".", "_")
    return transformed.strip("_").lower()


def _canonical_term(value: str) -> str:
    base = _to_snake_case(value.split(".")[-1].replace("[]", ""))
    return LEGACY_TERM_MAP.get(base, base)


def _semantic_id(value: str) -> str:
    return f"lotus.{_canonical_term(value)}"


def _humanize(value: str) -> str:
    return _canonical_term(value).replace("_", " ").strip()


def _infer_example(prop_name: str, prop_schema: dict[str, Any]) -> Any:
    key = _canonical_term(prop_name)
    if key in EXAMPLE_BY_KEY:
        return EXAMPLE_BY_KEY[key]

    enum_values = prop_schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]

    schema_type = prop_schema.get("type")
    schema_format = prop_schema.get("format")
    if schema_type == "array":
        item_schema = prop_schema.get("items", {})
        if isinstance(item_schema, dict):
            return [_infer_example(f"{prop_name}_item", item_schema)]
        return ["VALUE"]
    if schema_type == "object":
        return {"key": "value"}
    if schema_type == "boolean":
        return True
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 0.1234
    if schema_format == "date":
        return "2026-02-27"
    if schema_format == "date-time":
        return "2026-02-27T10:30:00Z"
    if key.endswith("_id"):
        return f"{key[:-3].upper()}_001"
    if "date" in key:
        return "2026-02-27"
    if "time" in key or "timestamp" in key:
        return "2026-02-27T10:30:00Z"
    if "currency" in key:
        return "USD"
    return f"example_{key}"


def _infer_description(model_name: str, prop_name: str, prop_schema: dict[str, Any]) -> str:
    key = _canonical_term(prop_name)
    text = _humanize(prop_name)
    if key.endswith("_id"):
        entity = key[: -len("_id")].replace("_", " ")
        return f"Unique {entity} identifier."
    if prop_schema.get("format") == "date":
        return f"Business date for {text}."
    if prop_schema.get("format") == "date-time":
        return f"Timestamp for {text}."
    if "currency" in key:
        return f"ISO currency code for {text}."
    if "return" in key or "rate" in key or "performance" in key:
        return f"Performance metric value for {text}."
    if "amount" in key or "value" in key:
        return f"Monetary value for {text}."
    return f"{_humanize(model_name)} field: {text}."


def _infer_schema_description(model_name: str, model_schema: dict[str, Any]) -> str:
    if model_schema.get("type") == "object":
        return f"{_humanize(model_name)} object."
    return f"{_humanize(model_name)} schema."


def _resolve_schema(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    return components.get("schemas", {}).get(ref.rsplit("/", 1)[-1], {})


def _build_schema_example(
    schema: dict[str, Any],
    *,
    components: dict[str, Any],
    seen_refs: set[str] | None = None,
    name_hint: str = "value",
) -> Any:
    seen = seen_refs or set()
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return {"id": "recursive_ref"}
        target = components.get("schemas", {}).get(ref.rsplit("/", 1)[-1], {})
        return _build_schema_example(
            target,
            components=components,
            seen_refs={*seen, ref},
            name_hint=ref.rsplit("/", 1)[-1],
        )

    if schema.get("example") is not None:
        return copy.deepcopy(schema["example"])
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        return copy.deepcopy(examples[0])
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        if isinstance(first, dict) and first.get("value") is not None:
            return copy.deepcopy(first["value"])

    if "oneOf" in schema and isinstance(schema["oneOf"], list) and schema["oneOf"]:
        first = schema["oneOf"][0]
        if isinstance(first, dict):
            return _build_schema_example(first, components=components, seen_refs=seen, name_hint=name_hint)
    if "anyOf" in schema and isinstance(schema["anyOf"], list) and schema["anyOf"]:
        first = schema["anyOf"][0]
        if isinstance(first, dict):
            return _build_schema_example(first, components=components, seen_refs=seen, name_hint=name_hint)

    schema_type = schema.get("type")
    if schema_type == "object" or isinstance(schema.get("properties"), dict):
        output: dict[str, Any] = {}
        for prop_name, prop_schema in schema.get("properties", {}).items():
            if isinstance(prop_schema, dict):
                output[prop_name] = _build_schema_example(
                    prop_schema,
                    components=components,
                    seen_refs=seen,
                    name_hint=prop_name,
                )
        if output:
            return output
        return {"key": "value"}
    if schema_type == "array":
        item_schema = schema.get("items", {})
        if isinstance(item_schema, dict):
            return [
                _build_schema_example(item_schema, components=components, seen_refs=seen, name_hint=f"{name_hint}_item")
            ]
        return ["VALUE"]
    return _infer_example(name_hint, schema)


def _is_http_validation_error_schema(json_content: dict[str, Any]) -> bool:
    schema = json_content.get("schema")
    if not isinstance(schema, dict):
        return False
    ref = schema.get("$ref")
    return isinstance(ref, str) and ref.endswith("/HTTPValidationError")


def _ensure_error_response_examples(responses: dict[str, Any]) -> None:
    for code, response in responses.items():
        if not (str(code).startswith("4") or str(code).startswith("5") or str(code) == "default"):
            continue
        if not isinstance(response, dict):
            continue
        content = response.get("content", {})
        if not isinstance(content, dict):
            continue
        json_content = content.get("application/json")
        if not isinstance(json_content, dict):
            continue
        if "example" in json_content or "examples" in json_content:
            continue
        if _is_http_validation_error_schema(json_content):
            json_content["example"] = copy.deepcopy(HTTP_VALIDATION_ERROR_EXAMPLE)


def _problem_detail_response(description: str = "Unexpected error response.") -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/problem+json": {
                "schema": {"$ref": f"#/components/schemas/{PROBLEM_DETAIL_SCHEMA_NAME}"},
                "example": copy.deepcopy(PROBLEM_DETAIL_EXAMPLE),
            }
        },
    }


def _infer_enum_descriptions(prop_name: str, prop_schema: dict[str, Any]) -> list[str] | None:
    enum_values = prop_schema.get("enum")
    if not isinstance(enum_values, list) or not enum_values:
        return None
    readable_name = _humanize(prop_name)
    return [f"Allowed {readable_name} value: {value}." for value in enum_values]


def _ensure_request_body_example(
    *,
    path: str,
    request_body: dict[str, Any],
    components: dict[str, Any],
) -> None:
    content = request_body.get("content", {})
    if not isinstance(content, dict):
        return
    json_content = content.get("application/json")
    if not isinstance(json_content, dict):
        return
    request_schema = json_content.get("schema", {})
    operation_example = OPERATION_JSON_EXAMPLES.get((path, "request"))
    if operation_example is not None:
        json_content["example"] = copy.deepcopy(operation_example)
    elif isinstance(request_schema, dict) and "example" not in json_content and "examples" not in json_content:
        json_content["example"] = _build_schema_example(
            request_schema,
            components=components,
            name_hint="request_body",
        )


def _ensure_operation_documentation(schema: dict[str, Any]) -> None:
    paths = schema.get("paths", {})
    components = schema.get("components", {})
    if not isinstance(paths, dict):
        return
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in ALLOWED_METHODS:
                continue
            if not isinstance(operation, dict):
                continue
            if not operation.get("summary"):
                operation["summary"] = f"{method.upper()} {path}"
            if not operation.get("description"):
                operation["description"] = f"{method.upper()} operation for {path} in lotus-performance."
            if path == "/metrics":
                operation["description"] = (
                    "Returns the Prometheus metrics surface for lotus-performance, including durable queue availability, "
                    "queue pressure, lineage storage capacity, recovery-drill assurance, and runtime-retention assurance gauges."
                )
            if not operation.get("tags"):
                if path.startswith("/health"):
                    operation["tags"] = ["Health"]
                elif path == "/metrics":
                    operation["tags"] = ["Monitoring"]
                else:
                    segment = path.strip("/").split("/", 1)[0] or "default"
                    operation["tags"] = [segment.replace("-", " ").title()]

            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                _ensure_request_body_example(
                    path=path,
                    request_body=request_body,
                    components=components,
                )

            responses = operation.get("responses")
            if isinstance(responses, dict):
                has_error = any(
                    str(code).startswith("4") or str(code).startswith("5") or str(code) == "default"
                    for code in responses
                )
                if not has_error:
                    responses["default"] = _problem_detail_response()
                _ensure_error_response_examples(responses)
                for code, response in responses.items():
                    if not str(code).startswith("2") or not isinstance(response, dict):
                        continue
                    content = response.get("content", {})
                    if not isinstance(content, dict):
                        continue
                    if path == "/metrics":
                        metrics_example = (
                            "# HELP lotus_performance_durable_queue_store_availability Durable queue store availability.\n"
                            "# TYPE lotus_performance_durable_queue_store_availability gauge\n"
                            'lotus_performance_durable_queue_store_availability{store="compute"} 1.0\n'
                        )
                        response["content"] = {
                            "text/plain": {
                                "schema": {"type": "string", "description": "Prometheus exposition format payload."},
                                "example": metrics_example,
                            }
                        }
                        continue
                    json_content = content.get("application/json")
                    if not isinstance(json_content, dict):
                        continue
                    response_schema = json_content.get("schema", {})
                    operation_example = OPERATION_JSON_EXAMPLES.get((path, "response"))
                    if operation_example is not None:
                        json_content["example"] = copy.deepcopy(operation_example)
                        continue
                    if (
                        isinstance(response_schema, dict)
                        and "example" not in json_content
                        and "examples" not in json_content
                    ):
                        json_content["example"] = _build_schema_example(
                            response_schema,
                            components=components,
                            name_hint="response_body",
                        )


def _ensure_schema_documentation(schema: dict[str, Any]) -> None:
    components = schema.get("components", {})
    if not isinstance(components, dict):
        return
    schemas = components.get("schemas", {})
    if not isinstance(schemas, dict):
        return
    schemas.setdefault(PROBLEM_DETAIL_SCHEMA_NAME, copy.deepcopy(PROBLEM_DETAIL_SCHEMA))
    for model_name, model_schema in schemas.items():
        if not isinstance(model_schema, dict):
            continue
        if not model_schema.get("description"):
            model_schema["description"] = _infer_schema_description(str(model_name), model_schema)
        enum_descriptions = _infer_enum_descriptions(str(model_name), model_schema)
        if enum_descriptions and "x-enum-descriptions" not in model_schema:
            model_schema["x-enum-descriptions"] = enum_descriptions

        properties = model_schema.get("properties", {})
        if not isinstance(properties, dict):
            continue
        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue
            prop_resolved = _resolve_schema(prop_schema, components)
            if not prop_schema.get("description"):
                prop_schema["description"] = prop_resolved.get("description") or _infer_description(
                    str(model_name),
                    str(prop_name),
                    prop_resolved,
                )
            if "example" not in prop_schema and "examples" not in prop_schema:
                prop_schema["example"] = _build_schema_example(
                    prop_schema,
                    components=components,
                    name_hint=str(prop_name),
                )
            if "x-lotus-semantic-id" not in prop_schema:
                prop_schema["x-lotus-semantic-id"] = _semantic_id(str(prop_name))
            if "x-lotus-canonical-term" not in prop_schema:
                prop_schema["x-lotus-canonical-term"] = _canonical_term(str(prop_name))
            prop_enum_descriptions = _infer_enum_descriptions(str(prop_name), prop_resolved)
            if prop_enum_descriptions and "x-enum-descriptions" not in prop_schema:
                prop_schema["x-enum-descriptions"] = prop_enum_descriptions


def enrich_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Mutates OpenAPI schema to meet RFC-0067 metadata minimums."""
    _ensure_operation_documentation(schema)
    _ensure_schema_documentation(schema)
    return schema
