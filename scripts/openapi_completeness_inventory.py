from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app  # noqa: E402

ALLOWED_METHODS = {"get", "post", "put", "patch", "delete"}
ERROR_RESPONSE_PREFIXES = ("4", "5")


@dataclass(frozen=True)
class OpenApiCompletenessFinding:
    method: str
    path: str
    rule: str
    description: str
    response_code: str | None = None


def _operation_id(operation: Mapping[str, Any]) -> str:
    value = operation.get("operationId")
    return str(value) if value else ""


def _responses(operation: Mapping[str, Any]) -> Mapping[str, Any]:
    responses = operation.get("responses")
    return responses if isinstance(responses, Mapping) else {}


def _content(response_or_request_body: Mapping[str, Any]) -> Mapping[str, Any]:
    content = response_or_request_body.get("content")
    return content if isinstance(content, Mapping) else {}


def _json_media(content: Mapping[str, Any]) -> Mapping[str, Any] | None:
    json_media = content.get("application/json")
    return json_media if isinstance(json_media, Mapping) else None


def _has_json_example(content: Mapping[str, Any]) -> bool:
    json_media = _json_media(content)
    return bool(json_media and ("example" in json_media or "examples" in json_media))


def _has_success_response(operation: Mapping[str, Any]) -> bool:
    return any(str(code).startswith("2") for code in _responses(operation))


def _has_error_response(operation: Mapping[str, Any]) -> bool:
    return any(_is_error_response_code(str(code)) for code in _responses(operation))


def _is_error_response_code(code: str) -> bool:
    return code == "default" or code.startswith(ERROR_RESPONSE_PREFIXES)


def _schema_ref(schema: Mapping[str, Any] | None) -> str:
    if not schema:
        return ""
    ref = schema.get("$ref")
    return str(ref) if ref else ""


def _has_problem_detail_contract(response: Mapping[str, Any]) -> bool:
    content = _content(response)
    problem_media = content.get("application/problem+json")
    if isinstance(problem_media, Mapping):
        return True
    json_media = _json_media(content)
    schema = json_media.get("schema") if json_media else None
    return "Problem" in _schema_ref(schema) or "Error" in _schema_ref(schema)


def _success_json_responses(operation: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    success_responses: list[tuple[str, Mapping[str, Any]]] = []
    for code, response in _responses(operation).items():
        if not str(code).startswith("2") or not isinstance(response, Mapping):
            continue
        content = _content(response)
        if _json_media(content) is not None:
            success_responses.append((str(code), response))
    return success_responses


def _error_responses(operation: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    error_responses: list[tuple[str, Mapping[str, Any]]] = []
    for code, response in _responses(operation).items():
        if not _is_error_response_code(str(code)) or not isinstance(response, Mapping):
            continue
        error_responses.append((str(code), response))
    return error_responses


def _add(
    findings: list[OpenApiCompletenessFinding],
    *,
    method: str,
    path: str,
    rule: str,
    description: str,
    response_code: str | None = None,
) -> None:
    findings.append(
        OpenApiCompletenessFinding(
            method=method,
            path=path,
            rule=rule,
            description=description,
            response_code=response_code,
        )
    )


def collect_openapi_completeness_findings(schema: Mapping[str, Any]) -> list[OpenApiCompletenessFinding]:
    findings: list[OpenApiCompletenessFinding] = []
    paths = schema.get("paths")
    if not isinstance(paths, Mapping):
        return findings

    for path, methods in paths.items():
        if not isinstance(methods, Mapping):
            continue
        for method, operation in methods.items():
            method_lower = str(method).lower()
            if method_lower not in ALLOWED_METHODS or not isinstance(operation, Mapping):
                continue

            method_upper = method_lower.upper()
            path_text = str(path)
            if not operation.get("summary"):
                _add(
                    findings,
                    method=method_upper,
                    path=path_text,
                    rule="MISSING_SUMMARY",
                    description="Operation is missing a concise summary.",
                )
            if not operation.get("description"):
                _add(
                    findings,
                    method=method_upper,
                    path=path_text,
                    rule="MISSING_DESCRIPTION",
                    description="Operation is missing a usage-oriented description.",
                )
            if not operation.get("tags"):
                _add(
                    findings,
                    method=method_upper,
                    path=path_text,
                    rule="MISSING_TAGS",
                    description="Operation is missing governance tags.",
                )
            if not _operation_id(operation):
                _add(
                    findings,
                    method=method_upper,
                    path=path_text,
                    rule="MISSING_OPERATION_ID",
                    description="Operation is missing a stable operationId.",
                )

            if not _responses(operation):
                _add(
                    findings,
                    method=method_upper,
                    path=path_text,
                    rule="MISSING_RESPONSES",
                    description="Operation is missing response contracts.",
                )
                continue

            if not _has_success_response(operation):
                _add(
                    findings,
                    method=method_upper,
                    path=path_text,
                    rule="MISSING_SUCCESS_RESPONSE",
                    description="Operation is missing a 2xx response contract.",
                )
            if not _has_error_response(operation):
                _add(
                    findings,
                    method=method_upper,
                    path=path_text,
                    rule="MISSING_ERROR_RESPONSE",
                    description="Operation is missing a 4xx, 5xx, or default error response.",
                )

            for code, response in _success_json_responses(operation):
                if not _has_json_example(_content(response)):
                    _add(
                        findings,
                        method=method_upper,
                        path=path_text,
                        rule="MISSING_SUCCESS_JSON_EXAMPLE",
                        description="Successful JSON response is missing an OpenAPI example.",
                        response_code=code,
                    )

            request_body = operation.get("requestBody")
            if isinstance(request_body, Mapping):
                content = _content(request_body)
                if _json_media(content) is not None and not _has_json_example(content):
                    _add(
                        findings,
                        method=method_upper,
                        path=path_text,
                        rule="MISSING_REQUEST_JSON_EXAMPLE",
                        description="JSON request body is missing an OpenAPI example.",
                    )

            for code, response in _error_responses(operation):
                content = _content(response)
                json_media = _json_media(content)
                if json_media is not None and "schema" not in json_media:
                    _add(
                        findings,
                        method=method_upper,
                        path=path_text,
                        rule="ERROR_JSON_MISSING_SCHEMA",
                        description="JSON error response is missing an explicit schema.",
                        response_code=code,
                    )
                if json_media is not None and not _has_json_example(content):
                    _add(
                        findings,
                        method=method_upper,
                        path=path_text,
                        rule="ERROR_JSON_MISSING_EXAMPLE",
                        description="JSON error response is missing an OpenAPI example.",
                        response_code=code,
                    )
                if not _has_problem_detail_contract(response):
                    _add(
                        findings,
                        method=method_upper,
                        path=path_text,
                        rule="ERROR_RESPONSE_NOT_PROBLEM_DETAIL",
                        description="Error response does not expose application/problem+json or a named error/problem schema.",
                        response_code=code,
                    )

    return sorted(findings, key=lambda item: (item.rule, item.path, item.method, item.response_code or ""))


def _operation_count(schema: Mapping[str, Any]) -> int:
    paths = schema.get("paths")
    if not isinstance(paths, Mapping):
        return 0
    count = 0
    for methods in paths.values():
        if not isinstance(methods, Mapping):
            continue
        count += sum(
            1
            for method, operation in methods.items()
            if str(method).lower() in ALLOWED_METHODS and isinstance(operation, Mapping)
        )
    return count


def render_markdown(schema: Mapping[str, Any], findings: Sequence[OpenApiCompletenessFinding], *, limit: int) -> str:
    rule_counts = Counter(finding.rule for finding in findings)
    endpoint_counts = Counter(f"{finding.method} {finding.path}" for finding in findings)

    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| OpenAPI operations | {_operation_count(schema)} |",
        f"| API completeness findings | {len(findings)} |",
        f"| Distinct rules | {len(rule_counts)} |",
        f"| Endpoints with findings | {len(endpoint_counts)} |",
        "",
        "## Findings By Rule",
        "",
        "| Rule | Count |",
        "| --- | ---: |",
    ]
    for rule, count in sorted(rule_counts.items()):
        lines.append(f"| `{rule}` | {count} |")

    lines.extend(
        [
            "",
            "## Most Affected Endpoints",
            "",
            "| Endpoint | Findings |",
            "| --- | ---: |",
        ]
    )
    for endpoint, count in endpoint_counts.most_common(15):
        lines.append(f"| `{endpoint}` | {count} |")

    lines.extend(
        [
            "",
            "## Findings",
            "",
            "| Rank | Rule | Endpoint | Response | Description |",
            "| ---: | --- | --- | --- | --- |",
        ]
    )
    for index, finding in enumerate(findings[:limit], start=1):
        response = finding.response_code or ""
        lines.append(
            f"| {index} | `{finding.rule}` | `{finding.method} {finding.path}` | `{response}` | {finding.description} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Lotus OpenAPI completeness findings")
    parser.add_argument("--limit", type=int, default=80, help="Maximum rows in the findings table")
    args = parser.parse_args()

    schema = app.openapi()
    print(render_markdown(schema, collect_openapi_completeness_findings(schema), limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
