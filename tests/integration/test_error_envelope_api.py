from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_http_error_response_uses_machine_readable_envelope(client):
    response = client.get(
        f"/performance/executions/{uuid4()}",
        headers={"X-Correlation-Id": "corr-error-envelope"},
    )

    body = response.json()
    assert response.status_code == 404
    assert response.headers["X-Correlation-Id"] == "corr-error-envelope"
    assert body["detail"] == "Execution data not found for the given calculation_id."
    assert body["error_code"] == "RESOURCE_NOT_FOUND"
    assert body["message"] == "Execution data not found for the given calculation_id."
    assert body["correlation_id"] == "corr-error-envelope"
    assert body["source"] == "lotus-performance"
    assert body["retryable"] is False


def test_request_validation_error_response_uses_safe_envelope(client):
    response = client.post(
        "/performance/twr",
        json={},
        headers={"X-Correlation-Id": "corr-validation-envelope"},
    )

    body = response.json()
    assert response.status_code == 422
    assert response.headers["X-Correlation-Id"] == "corr-validation-envelope"
    assert body["detail"] == "Request validation failed."
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["message"] == "Request validation failed."
    assert body["correlation_id"] == "corr-validation-envelope"
    assert body["source"] == "lotus-performance"
    assert body["retryable"] is False
    assert body["validation_errors"]
