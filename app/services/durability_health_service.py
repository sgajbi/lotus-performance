from __future__ import annotations

from dataclasses import dataclass

from app.services.execution_registry import get_execution_registry

REQUIRED_DURABLE_TABLES = (
    "analytics_execution",
    "analytics_execution_stage",
    "analytics_upstream_snapshot",
    "analytics_compute_job",
    "analytics_async_result",
    "lineage_records",
    "lineage_payloads",
)


@dataclass(frozen=True)
class DurabilityHealthStatus:
    is_ready: bool
    status: str
    reason: str | None = None


def check_durable_metadata_store_ready() -> DurabilityHealthStatus:
    execution_registry = get_execution_registry()
    try:
        execution_registry.ping()
    except Exception:
        return DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        )
    available_tables = set(execution_registry.list_table_names())
    if any(table_name not in available_tables for table_name in REQUIRED_DURABLE_TABLES):
        return DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_schema_incomplete",
        )
    return DurabilityHealthStatus(is_ready=True, status="ready")
