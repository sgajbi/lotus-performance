from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect

from app.services.execution_registry import execution_registry

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
    try:
        execution_registry.ping()
    except Exception:
        return DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        )
    available_tables = set(inspect(execution_registry._engine).get_table_names())
    if any(table_name not in available_tables for table_name in REQUIRED_DURABLE_TABLES):
        return DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_schema_incomplete",
        )
    return DurabilityHealthStatus(is_ready=True, status="ready")
