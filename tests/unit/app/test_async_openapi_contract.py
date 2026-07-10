from __future__ import annotations

from typing import Any

from main import app

ASYNC_SUBMISSION_ROUTES = (
    ("/performance/twr", "TWRAcceptedResponse", "calculation_id", "/performance/twr/results/"),
    ("/performance/benchmark", "BenchmarkAcceptedResponse", "calculation_id", "/performance/benchmark/results/"),
    (
        "/performance/workspace-summary",
        "WorkspaceSummaryAcceptedResponse",
        "calculation_id",
        "/performance/workspace-summary/results/",
    ),
    (
        "/performance/contribution",
        "ContributionAcceptedResponse",
        "calculation_id",
        "/performance/contribution/results/",
    ),
    ("/performance/attribution", "AttributionAcceptedResponse", "calculation_id", "/performance/attribution/results/"),
    (
        "/integration/returns/series",
        "ReturnsSeriesAcceptedResponse",
        "calculation_id",
        "/integration/returns/series/results/",
    ),
    ("/performance/inspections/twr", "TWRInspectionAcceptedResponse", "inspection_id", "/performance/inspections/"),
)

ASYNC_RESULT_ROUTES = (
    (
        "/performance/twr/results/{calculation_id}",
        "TWRAcceptedResponse",
        "calculation_id",
        "/performance/twr/results/",
    ),
    (
        "/performance/benchmark/results/{calculation_id}",
        "BenchmarkAcceptedResponse",
        "calculation_id",
        "/performance/benchmark/results/",
    ),
    (
        "/performance/workspace-summary/results/{calculation_id}",
        "WorkspaceSummaryAcceptedResponse",
        "calculation_id",
        "/performance/workspace-summary/results/",
    ),
    (
        "/performance/contribution/results/{calculation_id}",
        "ContributionAcceptedResponse",
        "calculation_id",
        "/performance/contribution/results/",
    ),
    (
        "/performance/attribution/results/{calculation_id}",
        "AttributionAcceptedResponse",
        "calculation_id",
        "/performance/attribution/results/",
    ),
    (
        "/integration/returns/series/results/{calculation_id}",
        "ReturnsSeriesAcceptedResponse",
        "calculation_id",
        "/integration/returns/series/results/",
    ),
    (
        "/performance/inspections/{inspection_id}",
        "TWRInspectionAcceptedResponse",
        "inspection_id",
        "/performance/inspections/",
    ),
)


def test_async_submission_routes_document_accepted_response_contracts() -> None:
    spec = app.openapi()

    for path, accepted_schema_name, id_field_name, result_path_prefix in ASYNC_SUBMISSION_ROUTES:
        operation = spec["paths"][path]["post"]
        accepted_response = operation["responses"]["202"]

        assert _response_schema_name(accepted_response) == accepted_schema_name
        _assert_accepted_example(accepted_response, id_field_name, result_path_prefix)


def test_async_result_routes_document_pending_and_terminal_error_contracts() -> None:
    spec = app.openapi()

    for path, accepted_schema_name, id_field_name, result_path_prefix in ASYNC_RESULT_ROUTES:
        operation = spec["paths"][path]["get"]
        responses = operation["responses"]

        assert _response_schema_name(responses["202"]) == accepted_schema_name
        _assert_accepted_example(responses["202"], id_field_name, result_path_prefix)
        for status_code in ("404", "409"):
            assert _response_schema_name(responses[status_code]) == "ErrorDetailResponse"
            _assert_error_detail_example(responses[status_code], expected_retryable=False)


def _response_schema_name(response: dict[str, Any]) -> str:
    schema = response["content"]["application/json"]["schema"]
    return schema["$ref"].rpartition("/")[-1]


def _assert_accepted_example(response: dict[str, Any], id_field_name: str, result_path_prefix: str) -> None:
    retry_after_header = response["headers"]["Retry-After"]
    assert retry_after_header["schema"]["type"] == "integer"
    assert retry_after_header["schema"]["example"] == 1

    example = response["content"]["application/json"]["example"]
    assert example[id_field_name]
    assert example["poll_path"].startswith("/performance/executions/")
    assert example["result_path"].startswith(result_path_prefix)
    assert example[id_field_name] in example["poll_path"]
    assert example[id_field_name] in example["result_path"]
    assert example["recommended_poll_after_seconds"] == 1
    if "status" in example:
        assert example["status"] == "pending"


def _assert_error_detail_example(response: dict[str, Any], *, expected_retryable: bool) -> None:
    example = response["content"]["application/json"]["example"]
    assert example["detail"]
    assert example["error_code"]
    assert example["message"]
    assert example["source"] == "lotus-performance"
    assert example["retryable"] is expected_retryable
    assert example["correlation_id"].startswith("corr_")
    assert example["request_id"].startswith("req_")
    assert "remediation_hint" in example
