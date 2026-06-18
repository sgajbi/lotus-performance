from app.api.endpoints.health import _readiness_failure_response
from app.services.durability_health_service import DurabilityHealthStatus


def test_readiness_failure_response_includes_remediation_hint_for_known_reason():
    response = _readiness_failure_response(
        DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        )
    )

    assert response.status == "unavailable"
    assert response.reason == "durable_metadata_store_unreachable"
    assert response.remediation_hint is not None
    assert "database URL" in response.remediation_hint


def test_readiness_failure_response_uses_default_reason_without_hint():
    response = _readiness_failure_response(
        DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
        )
    )

    assert response.status == "unavailable"
    assert response.reason == "durability_check_failed"
    assert response.remediation_hint is None
