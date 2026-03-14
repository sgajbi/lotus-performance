from __future__ import annotations

import os
import tempfile
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
    settings = get_settings()
    storage_path = getattr(settings, "LINEAGE_STORAGE_PATH", None)
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
    if getattr(settings, "LINEAGE_STORAGE_HEALTHCHECK_WRITE_PROBE_ENABLED", True):
        if not _probe_lineage_storage_write(str(storage_path)):
            return DurabilityHealthStatus(
                is_ready=False,
                status="unavailable",
                reason="lineage_storage_write_probe_failed",
            )
    return DurabilityHealthStatus(is_ready=True, status="ready")


def _probe_lineage_storage_write(storage_path: str) -> bool:
    fd: int | None = None
    temp_path: str | None = None
    try:
        fd, temp_path = tempfile.mkstemp(
            dir=storage_path,
            prefix=".lotus-lineage-healthcheck-",
            suffix=".tmp",
        )
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(b"lotus-performance-lineage-healthcheck\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.remove(temp_path)
        temp_path = None
        return True
    except OSError:
        return False
    finally:
        if fd is not None:
            os.close(fd)
        if temp_path is not None and os.path.exists(temp_path):
            os.remove(temp_path)
