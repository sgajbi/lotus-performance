from fastapi.testclient import TestClient

from main import app


def test_integration_capabilities_default_contract():
    with TestClient(app) as client:
        response = client.get("/integration/capabilities?consumer_system=lotus-gateway&tenant_id=default")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "v1"
    assert body["source_service"] == "lotus-performance"
    assert body["consumer_system"] == "lotus-gateway"
    assert body["tenant_id"] == "default"
    assert body["supported_input_modes"] == ["stateful", "stateless"]
    assert len(body["features"]) >= 4
    assert len(body["workflows"]) >= 3
    features = {item["key"] for item in body["features"]}
    assert "pa.execution.stateful" in features
    assert "pa.execution.stateless" in features
    assert response.headers.get("X-Correlation-Id")
    assert response.headers.get("X-Request-Id")
    assert response.headers.get("X-Trace-Id")


def test_integration_capabilities_env_override(monkeypatch):
    monkeypatch.setenv("PA_CAP_ATTRIBUTION_ENABLED", "false")
    monkeypatch.setenv("PLATFORM_INPUT_MODE_STATELESS_ENABLED", "false")
    monkeypatch.setenv("PA_POLICY_VERSION", "tenant-a-v4")
    with TestClient(app) as client:
        response = client.get("/integration/capabilities?consumer_system=lotus-manage&tenant_id=tenant-a")

    assert response.status_code == 200
    body = response.json()
    assert body["consumer_system"] == "lotus-manage"
    assert body["tenant_id"] == "tenant-a"
    assert body["policy_version"] == "tenant-a-v4"
    features = {item["key"]: item["enabled"] for item in body["features"]}
    assert features["pa.analytics.attribution"] is False
    assert body["supported_input_modes"] == ["stateful"]


def test_integration_capabilities_limit_guardrails():
    with TestClient(app) as client:
        response = client.get(
            "/integration/capabilities?consumer_system=lotus-gateway&tenant_id=default&feature_limit=2&workflow_limit=1"
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["features"]) == 2
    assert len(body["workflows"]) == 1


def test_health_and_metrics_endpoints_available():
    with TestClient(app) as client:
        health = client.get("/health")
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        metrics = client.get("/metrics")

    assert health.status_code == 200
    assert live.status_code == 200
    assert ready.status_code == 200
    assert health.json() == {"status": "ok"}
    assert live.json() == {"status": "live"}
    assert ready.json() == {"status": "ready"}
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text or "http_request_duration" in metrics.text


def test_health_ready_returns_503_when_draining():
    with TestClient(app) as client:
        app.state.is_draining = True
        response = client.get("/health/ready")
    app.state.is_draining = False

    assert response.status_code == 503
    assert response.json() == {"status": "draining"}
