from __future__ import annotations

from app.services.durability_health_service import DurabilityHealthStatus

DURABLE_METADATA_STORE_UNREACHABLE_REASON = "durable_metadata_store_unreachable"
LINEAGE_STORAGE_UNAVAILABLE_REASON = "lineage_storage_unavailable"


def durable_metadata_unavailable_reason(durability_status: DurabilityHealthStatus) -> str:
    return durability_status.reason or DURABLE_METADATA_STORE_UNREACHABLE_REASON


def lineage_storage_unavailable_reason(lineage_storage_status: DurabilityHealthStatus) -> str:
    return lineage_storage_status.reason or LINEAGE_STORAGE_UNAVAILABLE_REASON
