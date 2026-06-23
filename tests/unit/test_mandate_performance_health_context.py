from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from app.models.mandate_health import MandatePerformanceHealthContextRequest
from app.observability import correlation_id_var
from app.services.mandate_health_context_service import evaluate_mandate_performance_health_context
from main import app


def _request_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-02-27",
        "period_name": "YTD",
        "portfolio_period_return": "0.20",
        "benchmark_period_return": "1.50",
        "active_return_attention_threshold": "-1.00",
    }
    payload.update(overrides)
    return payload


def test_mandate_performance_health_context_flags_source_owned_underperformance() -> None:
    request = MandatePerformanceHealthContextRequest.model_validate(_request_payload())

    correlation_token = correlation_id_var.set("corr-mandate-health-unit")
    try:
        response = evaluate_mandate_performance_health_context(request)
    finally:
        correlation_id_var.reset(correlation_token)

    assert response.product_name == "MandatePerformanceHealthContext"
    assert response.product_version == "v1"
    assert response.correlation_id == "corr-mandate-health-unit"
    assert response.portfolio_id == "PB_SG_GLOBAL_BAL_001"
    assert response.period_name == "YTD"
    assert response.health_state == "attention"
    assert response.threshold_breached is True
    assert response.active_return_attention_threshold == Decimal("-1.00")
    assert response.source_metric.metric_name == "ACTIVE_RETURN"
    assert response.source_metric.active_return == Decimal("-1.30")
    assert response.methodology_posture.source_service == "lotus-performance"
    assert response.methodology_posture.source_metrics_product == "TimeWeightedReturnAnalytics:v1"
    assert response.methodology_posture.source_route == "/performance/twr"
    assert response.source_services == ["lotus-performance"]
    assert response.benchmark_context.benchmark_available is True
    assert response.request_fingerprint.startswith("sha256:")
    assert "PERFORMANCE_METHODOLOGY_SOURCE_OWNED" in response.reason_codes
    assert "MANDATE_PERFORMANCE_HEALTH_ACTIVE_RETURN_SOURCE_READY" in response.reason_codes
    assert "MANDATE_PERFORMANCE_HEALTH_ACTIVE_RETURN_THRESHOLD_BREACHED" in response.reason_codes


def test_mandate_performance_health_context_is_unavailable_without_benchmark() -> None:
    request = MandatePerformanceHealthContextRequest.model_validate(_request_payload(benchmark_period_return=None))

    response = evaluate_mandate_performance_health_context(request)

    assert response.health_state == "unavailable"
    assert response.threshold_breached is None
    assert response.source_metric.active_return is None
    assert response.benchmark_context.benchmark_available is False
    assert "MANDATE_PERFORMANCE_HEALTH_ACTIVE_RETURN_UNAVAILABLE" in response.reason_codes


def test_mandate_performance_health_context_endpoint_returns_source_product() -> None:
    client = TestClient(app)

    response = client.post(
        "/performance/mandate-health-context",
        json=_request_payload(),
        headers={"X-Correlation-Id": "corr-mandate-health-api"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["product_name"] == "MandatePerformanceHealthContext"
    assert body["correlation_id"] == "corr-mandate-health-api"
    assert body["methodology_posture"]["source_service"] == "lotus-performance"
    assert body["methodology_posture"]["source_metrics_product"] == "TimeWeightedReturnAnalytics:v1"
    assert body["source_services"] == ["lotus-performance"]
    assert body["benchmark_context"]["benchmark_available"] is True
    assert body["health_state"] == "attention"
    assert body["threshold_breached"] is True


def test_capabilities_include_mandate_performance_health_context_workflow() -> None:
    client = TestClient(app)

    response = client.get("/integration/capabilities?consumer_system=lotus-manage")

    assert response.status_code == 200
    body = response.json()
    surfaces = {surface["key"]: surface for surface in body["analytics_surfaces"]}
    features = {feature["key"]: feature for feature in body["features"]}
    workflows = {workflow["workflow_key"]: workflow for workflow in body["workflows"]}

    surface = surfaces["mandate_performance_health_context"]
    assert surface["path"] == "/performance/mandate-health-context"
    assert surface["supported_input_modes"] == ["stateless"]
    assert surface["supports_async"] is False
    assert "orders, OMS, or execution instructions" in " ".join(surface["contract_notes"])
    assert features["performance.integration.mandate_performance_health_context"]["enabled"] is True
    assert workflows["mandate_performance_health_context"]["required_features"] == [
        "performance.analytics.twr",
        "performance.integration.mandate_performance_health_context",
    ]
