import re
from uuid import uuid4

from fastapi.testclient import TestClient

from app.services.compute_job_store import compute_job_store
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import lineage_metadata_store
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


def test_health_ready_returns_503_when_durable_metadata_store_is_unavailable(mocker):
    mocker.patch(
        "app.api.endpoints.health.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "reason": "durable_metadata_store_unreachable",
    }


def test_metrics_include_durable_queue_pressure_signals():
    compute_job_store.create_schema()
    lineage_metadata_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()

    compute_job_store.enqueue_job(
        calculation_id=uuid4(),
        analytics_type="ReturnsSeries",
        request_payload={"portfolio_id": "PF-001"},
    )
    lineage_metadata_store.enqueue_lineage_payload(
        calculation_id=uuid4(),
        calculation_type="TWR",
        request_json="{}",
        response_json="{}",
        details={"request_payload.json": "request.json"},
    )

    with TestClient(app) as client:
        metrics = client.get("/metrics")

    compute_job_store.clear_all_records()
    lineage_metadata_store.clear_all_records()

    assert metrics.status_code == 200
    assert "lotus_performance_compute_queue_jobs" in metrics.text
    assert "lotus_performance_compute_queue_failure_pressure_jobs" in metrics.text
    assert 'lotus_performance_compute_queue_jobs{status="pending"} 1.0' in metrics.text, metrics.text
    assert "lotus_performance_compute_queue_oldest_leased_age_seconds" in metrics.text
    assert "lotus_performance_compute_queue_oldest_running_age_seconds" in metrics.text
    lineage_match = re.search(r"lotus_performance_lineage_queue_pending_payloads ([0-9]+(?:\.[0-9]+)?)", metrics.text)
    assert lineage_match is not None, metrics.text
    assert float(lineage_match.group(1)) >= 1.0
