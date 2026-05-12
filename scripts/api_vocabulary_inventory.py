from __future__ import annotations

import json
import re
import sys
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import app  # noqa: E402

ALLOWED_METHODS = {"get", "post", "put", "patch", "delete"}
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "standards" / "api-vocabulary" / "lotus-performance-api-vocabulary.v1.json"
PLACEHOLDER_EXAMPLES = {
    "example",
    "sample",
    "string",
    "value",
    "test",
    "foo",
    "bar",
    "baz",
    "placeholder",
}
LEGACY_TERM_MAP: dict[str, str] = {
    "cif_id": "client_id",
    "booking_center": "booking_center_code",
}


def _to_snake_case(value: str) -> str:
    transformed = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    transformed = transformed.replace("-", "_").replace(" ", "_").replace(".", "_")
    transformed = transformed.strip("_")
    return transformed.lower()


def _canonical_term(name: str) -> str:
    base = _to_snake_case(name.split(".")[-1].replace("[]", ""))
    return LEGACY_TERM_MAP.get(base, base)


def _semantic_id(name: str) -> str:
    return f"lotus.{_canonical_term(name)}"


def _schema_type(schema: dict[str, Any]) -> str:
    schema = _unwrap_nullable_schema(schema)
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    return str(schema.get("type", "object"))


def _unwrap_nullable_schema(schema: dict[str, Any]) -> dict[str, Any]:
    variants = schema.get("anyOf") or schema.get("oneOf")
    if not isinstance(variants, list):
        return schema
    non_null_variants = [variant for variant in variants if isinstance(variant, dict) and variant.get("type") != "null"]
    if len(non_null_variants) == 1 and non_null_variants[0].get("type") in {
        "boolean",
        "integer",
        "number",
        "string",
    }:
        return non_null_variants[0]
    return schema


def _resolve_schema(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    return components.get("schemas", {}).get(ref.rsplit("/", 1)[-1], {})


def _fallback_description(name: str) -> str:
    readable = _canonical_term(name).replace("_", " ")
    return f"Canonical {readable} used by lotus-performance APIs."


def _fallback_example(name: str, schema: dict[str, Any]) -> Any:
    schema = _unwrap_nullable_schema(schema)
    canonical = _canonical_term(name)
    schema_type = schema.get("type")
    schema_format = schema.get("format")
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]
    if schema_format == "date":
        return "2025-03-31"
    if schema_format == "date-time":
        return "2025-03-31T00:00:00Z"
    if canonical.endswith("_id"):
        return "ENTITY_001"
    if canonical.endswith("_date"):
        return "2025-03-31"
    if schema_type == "boolean":
        return True
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 0.1
    if schema_type == "array":
        return ["STANDARD_VALUE"]
    if schema_type == "object":
        return {"key": "value"}
    return "STANDARD_VALUE"


def _extract_fields(
    schema: dict[str, Any],
    *,
    components: dict[str, Any],
    prefix: str = "",
    location: str = "body",
) -> list[dict[str, Any]]:
    resolved = _resolve_schema(schema, components)
    properties = resolved.get("properties", {})
    required = set(resolved.get("required", []))
    if not isinstance(properties, dict):
        return []

    fields: list[dict[str, Any]] = []
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue
        prop_resolved = _resolve_schema(_unwrap_nullable_schema(prop_schema), components)
        field_name = f"{prefix}.{prop_name}" if prefix else prop_name
        field = {
            "name": field_name,
            "location": location,
            "required": prop_name in required,
            "type": _schema_type(prop_schema),
            "semanticId": _semantic_id(prop_name),
            "attributeRef": f"#/attributeCatalog/{_semantic_id(prop_name)}",
            "description": prop_resolved.get("description") or _fallback_description(field_name),
            "example": (
                prop_resolved.get("example")
                if prop_resolved.get("example") is not None
                else _fallback_example(field_name, prop_resolved)
            ),
        }
        fields.append(field)

        nested_type = prop_resolved.get("type")
        if nested_type == "object" or "$ref" in prop_schema:
            fields.extend(
                _extract_fields(
                    prop_schema,
                    components=components,
                    prefix=field_name,
                    location=location,
                )
            )
        elif nested_type == "array":
            item_schema = prop_resolved.get("items")
            if isinstance(item_schema, dict):
                fields.extend(
                    _extract_fields(
                        item_schema,
                        components=components,
                        prefix=f"{field_name}[]",
                        location=location,
                    )
                )
    return fields


def _extract_request_fields(
    operation: dict[str, Any], components: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    request_fields: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []

    for parameter in operation.get("parameters", []):
        if not isinstance(parameter, dict):
            continue
        schema = parameter.get("schema", {})
        if not isinstance(schema, dict):
            schema = {}
        name = str(parameter.get("name", ""))
        canonical = _canonical_term(name)
        request_fields.append(
            {
                "name": name,
                "location": parameter.get("in", "query"),
                "required": bool(parameter.get("required", False)),
                "type": _schema_type(schema),
                "semanticId": _semantic_id(name),
                "attributeRef": f"#/attributeCatalog/{_semantic_id(name)}",
            }
        )
        controls.append(
            {
                "name": canonical,
                "kind": "request_option",
                "location": parameter.get("in", "query"),
                "required": bool(parameter.get("required", False)),
                "type": _schema_type(schema),
                "description": parameter.get("description") or schema.get("description") or _fallback_description(name),
                "example": parameter.get("example")
                if parameter.get("example") is not None
                else _fallback_example(name, schema),
                "allowedValues": schema.get("enum", []),
                "semanticId": _semantic_id(name),
                "attributeRef": f"#/attributeCatalog/{_semantic_id(name)}",
            }
        )

    request_body = operation.get("requestBody", {})
    if isinstance(request_body, dict):
        json_content = request_body.get("content", {}).get("application/json")
        if isinstance(json_content, dict):
            schema = json_content.get("schema", {})
            if isinstance(schema, dict):
                request_fields.extend(_extract_fields(schema, components=components))

    return request_fields, controls


def _extract_response_fields(operation: dict[str, Any], components: dict[str, Any]) -> list[dict[str, Any]]:
    responses = operation.get("responses", {})
    success_codes = sorted(code for code in responses if str(code).startswith("2"))
    if not success_codes:
        return []
    response = responses[success_codes[0]]
    if not isinstance(response, dict):
        return []
    json_content = response.get("content", {}).get("application/json")
    if not isinstance(json_content, dict):
        return []
    schema = json_content.get("schema", {})
    if not isinstance(schema, dict):
        return []
    return _extract_fields(schema, components=components)


def _domain(path: str, tags: list[str]) -> str:
    if tags:
        return _to_snake_case(tags[0])
    root = path.strip("/").split("/")[0] if path.strip("/") else "operational"
    return _to_snake_case(root)


def build_inventory() -> dict[str, Any]:
    schema = app.openapi()
    components = schema.get("components", {})

    attribute_catalog_map: dict[str, dict[str, Any]] = {}
    endpoints: list[dict[str, Any]] = []
    controls_catalog: list[dict[str, Any]] = []

    for path, methods in schema.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in ALLOWED_METHODS or not isinstance(operation, dict):
                continue

            request_fields, controls = _extract_request_fields(operation, components)
            response_fields = _extract_response_fields(operation, components)
            all_fields = request_fields + response_fields

            for field in all_fields:
                semantic_id = field["semanticId"]
                canonical = _canonical_term(field["name"])
                if semantic_id not in attribute_catalog_map:
                    attribute_catalog_map[semantic_id] = {
                        "semanticId": semantic_id,
                        "canonicalTerm": canonical,
                        "preferredName": canonical,
                        "description": field.get("description") or _fallback_description(field["name"]),
                        "example": field.get("example"),
                        "type": field.get("type", "string"),
                        "locations": [field.get("location", "body")],
                        "observedTypes": [field.get("type", "string")],
                    }
                else:
                    item = attribute_catalog_map[semantic_id]
                    location = field.get("location", "body")
                    observed_type = field.get("type", "string")
                    if location not in item["locations"]:
                        item["locations"].append(location)
                    if observed_type not in item["observedTypes"]:
                        item["observedTypes"].append(observed_type)

            endpoint_request_fields = [
                {
                    "name": field["name"],
                    "location": field["location"],
                    "required": field["required"],
                    "type": field["type"],
                    "semanticId": field["semanticId"],
                    "attributeRef": field["attributeRef"],
                }
                for field in request_fields
            ]
            endpoint_response_fields = [
                {
                    "name": field["name"],
                    "location": field["location"],
                    "required": field["required"],
                    "type": field["type"],
                    "semanticId": field["semanticId"],
                    "attributeRef": field["attributeRef"],
                }
                for field in response_fields
            ]

            endpoints.append(
                {
                    "domain": _domain(path, operation.get("tags", [])),
                    "method": method.upper(),
                    "path": path,
                    "operationId": operation.get("operationId"),
                    "summary": operation.get("summary") or "",
                    "request": {"fields": endpoint_request_fields},
                    "response": {"fields": endpoint_response_fields},
                }
            )
            controls_catalog.extend(controls)

    return {
        "specVersion": "1.0.0",
        "application": "lotus-performance",
        "sourceOpenApi": [
            {
                "service": "lotus-performance",
                "version": schema.get("info", {}).get("version", "0.1.0"),
                "openApiVersion": schema.get("openapi", "3.1.0"),
            }
        ],
        "generatedAt": datetime.now(UTC).isoformat(),
        "attributeCatalog": sorted(attribute_catalog_map.values(), key=lambda x: x["semanticId"]),
        "controlsCatalog": controls_catalog,
        "endpoints": endpoints,
    }


def _is_snake_case(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9_]*", value))


def _is_placeholder_example(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in PLACEHOLDER_EXAMPLES
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0].strip().lower() in PLACEHOLDER_EXAMPLES
    return False


def validate_inventory(inventory: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    semantic_ids: set[str] = set()
    for attr in inventory.get("attributeCatalog", []):
        semantic_id = str(attr.get("semanticId", ""))
        canonical = str(attr.get("canonicalTerm", ""))
        preferred = str(attr.get("preferredName", ""))
        if not semantic_id:
            errors.append("attributeCatalog entry missing semanticId")
            continue
        if semantic_id in semantic_ids:
            errors.append(f"duplicate semanticId: {semantic_id}")
        semantic_ids.add(semantic_id)
        if canonical != preferred:
            errors.append(f"canonicalTerm/preferredName mismatch: {semantic_id}")
        if not _is_snake_case(canonical):
            errors.append(f"canonicalTerm must be snake_case: {semantic_id} -> {canonical}")
        if canonical in LEGACY_TERM_MAP:
            errors.append(f"legacy term is not allowed: {canonical} (use {LEGACY_TERM_MAP[canonical]})")
        if _is_placeholder_example(attr.get("example")):
            errors.append(f"generic placeholder example is not allowed: {semantic_id}")

    for endpoint in inventory.get("endpoints", []):
        request_fields = endpoint.get("request", {}).get("fields", [])
        response_fields = endpoint.get("response", {}).get("fields", [])
        for field in [*request_fields, *response_fields]:
            for forbidden in ("description", "example", "canonicalTerm", "preferredName"):
                if forbidden in field:
                    errors.append(
                        f"endpoint field duplicates attribute metadata ({forbidden}): "
                        f"{endpoint.get('method')} {endpoint.get('path')}::{field.get('name')}"
                    )
            if not field.get("semanticId"):
                errors.append(
                    f"endpoint field missing semanticId: {endpoint.get('method')} {endpoint.get('path')}::{field.get('name')}"
                )
            if not field.get("attributeRef"):
                errors.append(
                    f"endpoint field missing attributeRef: {endpoint.get('method')} {endpoint.get('path')}::{field.get('name')}"
                )

    return errors


def _normalize_for_compare(payload: dict[str, Any]) -> dict[str, Any]:
    clone = dict(payload)
    clone.pop("generatedAt", None)
    return clone


def main() -> int:
    parser = ArgumentParser(description="Generate and validate lotus-performance API vocabulary inventory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    inventory = build_inventory()
    errors = validate_inventory(inventory)
    if errors:
        print("API vocabulary inventory validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.validate_only:
        if not output_path.exists():
            print(f"Inventory file missing: {output_path}")
            return 1
        on_disk = json.loads(output_path.read_text(encoding="utf-8"))
        if _normalize_for_compare(on_disk) != _normalize_for_compare(inventory):
            print("Inventory drift detected. Regenerate with:")
            print(f"python scripts/api_vocabulary_inventory.py --output {output_path}")
            return 1
        print("API vocabulary inventory gate passed (no drift).")
        return 0

    output_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote inventory: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
