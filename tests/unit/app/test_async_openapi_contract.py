from __future__ import annotations

from typing import Any

from main import app

ASYNC_SUBMISSION_ROUTES = (
    ("/performance/twr", "TWRAcceptedResponse", "/performance/twr/results/"),
    ("/performance/benchmark", "BenchmarkAcceptedResponse", "/performance/benchmark/results/"),
    (
        "/performance/workspace-summary",
        "WorkspaceSummaryAcceptedResponse",
        "/performance/workspace-summary/results/",
    ),
    ("/performance/contribution", "ContributionAcceptedResponse", "/performance/contribution/results/"),
    ("/performance/attribution", "AttributionAcceptedResponse", "/performance/attribution/results/"),
    ("/integration/returns/series", "ReturnsSeriesAcceptedResponse", "/integration/returns/series/results/"),
)

ASYNC_RESULT_ROUTES = (
    ("/performance/twr/results/{calculation_id}", "TWRAcceptedResponse", "/performance/twr/results/"),
    (
        "/performance/benchmark/results/{calculation_id}",
        "BenchmarkAcceptedResponse",
        "/performance/benchmark/results/",
    ),
    (
        "/performance/workspace-summary/results/{calculation_id}",
        "WorkspaceSummaryAcceptedResponse",
        "/performance/workspace-summary/results/",
    ),
    (
        "/performance/contribution/results/{calculation_id}",
        "ContributionAcceptedResponse",
        "/performance/contribution/results/",
    ),
    (
        "/performance/attribution/results/{calculation_id}",
        "AttributionAcceptedResponse",
        "/performance/attribution/results/",
    ),
    (
        "/integration/returns/series/results/{calculation_id}",
        "ReturnsSeriesAcceptedResponse",
        "/integration/returns/series/results/",
    ),
)


def test_async_submission_routes_document_accepted_response_contracts() -> None:
    spec = app.openapi()

    for path, accepted_schema_name, result_path_prefix in ASYNC_SUBMISSION_ROUTES:
        operation = spec["paths"][path]["post"]
        accepted_response = operation["responses"]["202"]

        assert _response_schema_name(accepted_response) == accepted_schema_name
        _assert_accepted_example(accepted_response, result_path_prefix)


def test_async_result_routes_document_pending_and_terminal_error_contracts() -> None:
    spec = app.openapi()

    for path, accepted_schema_name, result_path_prefix in ASYNC_RESULT_ROUTES:
        operation = spec["paths"][path]["get"]
        responses = operation["responses"]

        assert _response_schema_name(responses["202"]) == accepted_schema_name
        _assert_accepted_example(responses["202"], result_path_prefix)
        for status_code in ("404", "409"):
            assert _response_schema_name(responses[status_code]) == "ErrorDetailResponse"
            assert responses[status_code]["content"]["application/json"]["example"]["detail"]


def _response_schema_name(response: dict[str, Any]) -> str:
    schema = response["content"]["application/json"]["schema"]
    return schema["$ref"].rpartition("/")[-1]


def _assert_accepted_example(response: dict[str, Any], result_path_prefix: str) -> None:
    example = response["content"]["application/json"]["example"]
    assert example["calculation_id"]
    assert example["poll_path"].startswith("/performance/executions/")
    assert example["result_path"].startswith(result_path_prefix)
    assert example["calculation_id"] in example["poll_path"]
    assert example["calculation_id"] in example["result_path"]
    if "status" in example:
        assert example["status"] == "pending"
