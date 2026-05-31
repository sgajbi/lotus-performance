from app.services.durability_health_service import DurabilityHealthStatus
from app.services.runtime_unavailability import (
    DURABLE_METADATA_STORE_UNREACHABLE_REASON,
    durable_metadata_unavailable_reason,
)


def test_durable_metadata_unavailable_reason_preserves_specific_reason():
    status = DurabilityHealthStatus(is_ready=False, status="unavailable", reason="schema_incomplete")

    assert durable_metadata_unavailable_reason(status) == "schema_incomplete"


def test_durable_metadata_unavailable_reason_uses_fallback_when_reason_missing():
    status = DurabilityHealthStatus(is_ready=False, status="unavailable")

    assert durable_metadata_unavailable_reason(status) == DURABLE_METADATA_STORE_UNREACHABLE_REASON
