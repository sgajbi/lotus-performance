from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import get_settings
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
    lineage_storage_status = check_lineage_storage_ready()
    if not lineage_storage_status.is_ready:
        return lineage_storage_status
    return DurabilityHealthStatus(is_ready=True, status="ready")


def check_lineage_storage_ready() -> DurabilityHealthStatus:
    storage_path = getattr(get_settings(), "LINEAGE_STORAGE_PATH", None)
    if not storage_path or not os.path.exists(storage_path):
        return DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="lineage_storage_path_missing",
        )
    if not os.path.isdir(storage_path):
        return DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="lineage_storage_path_invalid",
        )
    if not os.access(storage_path, os.R_OK | os.W_OK | os.X_OK):
        return DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="lineage_storage_path_unreadable",
        )
    return DurabilityHealthStatus(is_ready=True, status="ready")
