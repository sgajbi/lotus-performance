from __future__ import annotations

from dataclasses import dataclass

from app.services.execution_registry import execution_registry


@dataclass(frozen=True)
class DurabilityHealthStatus:
    is_ready: bool
    status: str
    reason: str | None = None


def check_durable_metadata_store_ready() -> DurabilityHealthStatus:
    try:
        execution_registry.ping()
    except Exception:
        return DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        )
    return DurabilityHealthStatus(is_ready=True, status="ready")
