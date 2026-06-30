from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, cast

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
DEFAULT_DURABLE_READINESS_TIMEOUT_SECONDS = 2.0
DURABLE_METADATA_READINESS_TIMEOUT_REASON = "durable_metadata_readiness_timeout"
DURABLE_METADATA_SCHEMA_DISCOVERY_FAILED_REASON = "durable_metadata_schema_discovery_failed"
LINEAGE_STORAGE_READINESS_TIMEOUT_REASON = "lineage_storage_readiness_timeout"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DurabilityHealthStatus:
    is_ready: bool
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class LineageStorageCapacitySnapshot:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    free_ratio: float
    used_ratio: float


def check_durable_metadata_store_ready() -> DurabilityHealthStatus:
    metadata_store_status = check_durable_metadata_schema_ready()
    if not metadata_store_status.is_ready:
        return metadata_store_status
    lineage_storage_status = check_lineage_storage_ready()
    if not lineage_storage_status.is_ready:
        return lineage_storage_status
    return _ready_status()


async def check_durable_metadata_store_ready_async(
    *,
    timeout_seconds: float | None = None,
) -> DurabilityHealthStatus:
    timeout = _durable_readiness_timeout_seconds(timeout_seconds)
    metadata_store_status = await _bounded_readiness_probe(
        check_durable_metadata_schema_ready,
        timeout_seconds=timeout,
        timeout_reason=DURABLE_METADATA_READINESS_TIMEOUT_REASON,
    )
    if not metadata_store_status.is_ready:
        return metadata_store_status
    lineage_storage_status = await _bounded_readiness_probe(
        check_lineage_storage_ready,
        timeout_seconds=timeout,
        timeout_reason=LINEAGE_STORAGE_READINESS_TIMEOUT_REASON,
    )
    if not lineage_storage_status.is_ready:
        return lineage_storage_status
    return _ready_status()


async def _bounded_readiness_probe(
    probe: Callable[[], DurabilityHealthStatus],
    *,
    timeout_seconds: float,
    timeout_reason: str,
) -> DurabilityHealthStatus:
    try:
        return await asyncio.wait_for(asyncio.to_thread(probe), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning(
            "Durable readiness probe timed out.",
            extra={"timeout_seconds": timeout_seconds, "reason": timeout_reason},
        )
        return _unavailable_status(timeout_reason)


def _durable_readiness_timeout_seconds(timeout_seconds: float | None = None) -> float:
    configured_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else getattr(get_settings(), "DURABLE_READINESS_TIMEOUT_SECONDS", DEFAULT_DURABLE_READINESS_TIMEOUT_SECONDS)
    )
    if configured_timeout <= 0:
        return DEFAULT_DURABLE_READINESS_TIMEOUT_SECONDS
    configured_timeout_float = cast(float, configured_timeout)
    return configured_timeout_float


def check_durable_metadata_schema_ready() -> DurabilityHealthStatus:
    execution_registry = get_execution_registry()
    try:
        execution_registry.ping()
    except Exception:
        logger.warning("Durable metadata store readiness ping failed.", exc_info=True)
        return _unavailable_status("durable_metadata_store_unreachable")
    try:
        available_tables = set(execution_registry.list_table_names())
    except Exception:
        logger.warning("Durable metadata schema table discovery failed.", exc_info=True)
        return _unavailable_status(DURABLE_METADATA_SCHEMA_DISCOVERY_FAILED_REASON)
    if any(table_name not in available_tables for table_name in REQUIRED_DURABLE_TABLES):
        return _unavailable_status("durable_metadata_schema_incomplete")
    return _ready_status()


def check_lineage_storage_ready() -> DurabilityHealthStatus:
    settings = get_settings()
    storage_path = getattr(settings, "LINEAGE_STORAGE_PATH", None)
    path_status = _lineage_storage_path_unavailable_status(storage_path)
    if path_status is not None:
        return path_status
    if getattr(settings, "LINEAGE_STORAGE_HEALTHCHECK_WRITE_PROBE_ENABLED", True):
        if not _probe_lineage_storage_write(str(storage_path)):
            return _unavailable_status("lineage_storage_write_probe_failed")
    return _ready_status()


def _lineage_storage_path_unavailable_status(storage_path: Any) -> DurabilityHealthStatus | None:
    failure_reason = _lineage_storage_path_failure_reason(storage_path)
    if failure_reason is not None:
        return _unavailable_status(failure_reason)
    return None


def _lineage_storage_path_failure_reason(storage_path: Any) -> str | None:
    path_failure_checks: tuple[tuple[str, Callable[[Any], bool]], ...] = (
        ("lineage_storage_path_missing", _is_missing_lineage_storage_path),
        ("lineage_storage_path_invalid", _is_invalid_lineage_storage_path),
        ("lineage_storage_path_unreadable", _is_unreadable_lineage_storage_path),
    )
    for reason, is_failure in path_failure_checks:
        if is_failure(storage_path):
            return reason
    return None


def _is_missing_lineage_storage_path(storage_path: Any) -> bool:
    return not storage_path or not os.path.exists(storage_path)


def _is_invalid_lineage_storage_path(storage_path: Any) -> bool:
    return not os.path.isdir(storage_path)


def _is_unreadable_lineage_storage_path(storage_path: Any) -> bool:
    return not os.access(storage_path, os.R_OK | os.W_OK | os.X_OK)


def get_lineage_storage_capacity() -> LineageStorageCapacitySnapshot:
    settings = get_settings()
    storage_path = getattr(settings, "LINEAGE_STORAGE_PATH", None)
    if not storage_path:
        raise FileNotFoundError("lineage storage path is not configured")
    usage = shutil.disk_usage(storage_path)
    total_bytes = int(usage.total)
    used_bytes = int(usage.used)
    free_bytes = int(usage.free)
    if total_bytes <= 0:
        free_ratio = 0.0
        used_ratio = 0.0
    else:
        free_ratio = free_bytes / total_bytes
        used_ratio = used_bytes / total_bytes
    return LineageStorageCapacitySnapshot(
        total_bytes=total_bytes,
        used_bytes=used_bytes,
        free_bytes=free_bytes,
        free_ratio=free_ratio,
        used_ratio=used_ratio,
    )


def _ready_status() -> DurabilityHealthStatus:
    return DurabilityHealthStatus(is_ready=True, status="ready")


def _unavailable_status(reason: str) -> DurabilityHealthStatus:
    return DurabilityHealthStatus(is_ready=False, status="unavailable", reason=reason)


def _probe_lineage_storage_write(storage_path: str) -> bool:
    fd: int | None = None
    temp_path: str | None = None
    try:
        fd, temp_path = tempfile.mkstemp(
            dir=storage_path,
            prefix=".lotus-lineage-healthcheck-",
            suffix=".tmp",
        )
        _write_lineage_storage_probe_file(fd)
        fd = None
        os.remove(temp_path)
        temp_path = None
        return True
    except OSError:
        logger.warning("Lineage storage write probe failed.", exc_info=True)
        return False
    finally:
        _cleanup_lineage_storage_probe(fd, temp_path)


def _write_lineage_storage_probe_file(fd: int) -> None:
    with os.fdopen(fd, "wb") as handle:
        handle.write(b"lotus-performance-lineage-healthcheck\n")
        handle.flush()
        os.fsync(handle.fileno())


def _cleanup_lineage_storage_probe(fd: int | None, temp_path: str | None) -> None:
    if fd is not None:
        os.close(fd)
    if temp_path is not None and os.path.exists(temp_path):
        os.remove(temp_path)
