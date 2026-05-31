from __future__ import annotations

from app.services.durability_health_service import DurabilityHealthStatus

DURABLE_METADATA_STORE_UNREACHABLE_REASON = "durable_metadata_store_unreachable"


def durable_metadata_unavailable_reason(durability_status: DurabilityHealthStatus) -> str:
    return durability_status.reason or DURABLE_METADATA_STORE_UNREACHABLE_REASON
