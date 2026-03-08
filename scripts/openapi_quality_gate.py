"""Enforce RFC-0067 OpenAPI quality for lotus-performance."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import app  # noqa: E402

ALLOWED_METHODS = {"get", "post", "put", "patch", "delete"}


def _has_success_response(operation: dict[str, Any]) -> bool:
    responses = operation.get("responses", {})
    return any(str(code).startswith("2") for code in responses)


def _has_error_response(operation: dict[str, Any]) -> bool:
    responses = operation.get("responses", {})
    return any(str(code).startswith("4") or str(code).startswith("5") or str(code) == "default" for code in responses)


def _has_json_example(content: dict[str, Any]) -> bool:
    json_content = content.get("application/json", {})
    if not isinstance(json_content, dict):
        return False
    return "example" in json_content or "examples" in json_content


def _is_ref_only(prop_schema: dict[str, Any]) -> bool:
    return set(prop_schema.keys()) == {"$ref"}


def evaluate_schema(schema: dict[str, Any], *, service_name: str) -> list[str]:
    errors: list[str] = []
    missing_docs: list[tuple[str, str, str]] = []
    missing_fields: list[tuple[str, str, str]] = []
    operation_ids: list[str] = []

    for path, methods in schema.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in ALLOWED_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            method_upper = method.upper()
            operation_id = operation.get("operationId")
            if operation_id:
                operation_ids.append(str(operation_id))

            if not operation.get("summary"):
                missing_docs.append((method_upper, path, "summary"))
            if not operation.get("description"):
                missing_docs.append((method_upper, path, "description"))
            if not operation.get("tags"):
                missing_docs.append((method_upper, path, "tags"))

            if not operation.get("responses"):
                missing_docs.append((method_upper, path, "responses"))
            else:
                if not _has_success_response(operation):
                    missing_docs.append((method_upper, path, "2xx response"))
                if not _has_error_response(operation):
                    missing_docs.append((method_upper, path, "error response (4xx/5xx/default)"))
                for code, response in operation.get("responses", {}).items():
                    if not str(code).startswith("2") or not isinstance(response, dict):
                        continue
                    content = response.get("content", {})
                    if isinstance(content, dict) and "application/json" in content and not _has_json_example(content):
                        missing_docs.append((method_upper, path, f"{code} application/json example"))

            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content", {})
                if isinstance(content, dict) and "application/json" in content and not _has_json_example(content):
                    missing_docs.append((method_upper, path, "requestBody application/json example"))

    schemas = schema.get("components", {}).get("schemas", {})
    if isinstance(schemas, dict):
        for model_name, model_schema in schemas.items():
            if not isinstance(model_schema, dict):
                continue
            properties = model_schema.get("properties", {})
            if not isinstance(properties, dict):
                continue
            for prop_name, prop_schema in properties.items():
                if not isinstance(prop_schema, dict):
                    continue
                if _is_ref_only(prop_schema):
                    continue
                if not prop_schema.get("description"):
                    missing_fields.append((str(model_name), str(prop_name), "description"))
                if "example" not in prop_schema and "examples" not in prop_schema:
                    missing_fields.append((str(model_name), str(prop_name), "example"))
                if not prop_schema.get("x-lotus-semantic-id"):
                    missing_fields.append((str(model_name), str(prop_name), "x-lotus-semantic-id"))
                if not prop_schema.get("x-lotus-canonical-term"):
                    missing_fields.append((str(model_name), str(prop_name), "x-lotus-canonical-term"))

    if missing_docs:
        errors.append(f"OpenAPI quality gate ({service_name}): missing endpoint documentation/response contract")
        errors.extend(f"  - {method} {path}: missing {field}" for method, path, field in missing_docs)

    if missing_fields:
        errors.append(f"OpenAPI quality gate ({service_name}): missing schema field metadata")
        errors.extend(f"  - {model}.{field}: missing {field_name}" for model, field, field_name in missing_fields)

    duplicate_operation_ids = sorted(
        [operation_id for operation_id, count in Counter(operation_ids).items() if count > 1]
    )
    if duplicate_operation_ids:
        errors.append(f"OpenAPI quality gate ({service_name}): duplicate operationId values")
        errors.extend(f"  - {operation_id}" for operation_id in duplicate_operation_ids)

    return errors


def main() -> int:
    schema = app.openapi()
    if "paths" not in schema or not schema["paths"]:
        print("OpenAPI quality gate (lotus-performance): no paths found")
        return 1

    errors = evaluate_schema(schema, service_name="lotus-performance")
    if errors:
        print("\n".join(errors))
        return 1

    print("OpenAPI quality gate passed for lotus-performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
