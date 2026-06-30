from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _assert_security_headers(response):
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert "Strict-Transport-Security" not in response.headers


def test_security_headers_are_present_on_success_response(client):
    response = client.get("/health")

    assert response.status_code == 200
    _assert_security_headers(response)


def test_security_headers_are_present_on_error_response(client):
    response = client.get(f"/performance/executions/{uuid4()}")

    assert response.status_code == 404
    _assert_security_headers(response)


def test_cors_policy_allows_configured_local_origin(client):
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"


def test_cors_preflight_allows_enterprise_browser_flow_headers(client):
    requested_headers = [
        "Authorization",
        "Content-Type",
        "X-Actor-Id",
        "X-Tenant-Id",
        "X-Role",
        "X-Service-Identity",
        "X-Capabilities",
        "X-Portfolio-Id",
        "X-Correlation-Id",
        "X-Request-Id",
        "X-Trace-Id",
    ]

    response = client.options(
        "/performance/executions/00000000-0000-0000-0000-000000000000",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": ", ".join(requested_headers),
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    allowed_headers = {
        header.strip().lower()
        for header in response.headers["Access-Control-Allow-Headers"].split(",")
        if header.strip()
    }
    assert {header.lower() for header in requested_headers} <= allowed_headers


def test_trusted_host_policy_denies_unconfigured_host(client):
    response = client.get("/health", headers={"Host": "evil.example"})

    assert response.status_code == 400
    assert "Invalid host header" in response.text
