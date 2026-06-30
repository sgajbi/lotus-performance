from __future__ import annotations

from app.services.runtime_unavailability import LINEAGE_STORAGE_CAPACITY_UNREADABLE_REASON

_REMEDIATION_HINTS: dict[str, str] = {
    "durable_metadata_store_unreachable": (
        "Verify the durable metadata database is reachable from the service and that the configured "
        "database URL, credentials, and network path are correct."
    ),
    "durable_metadata_schema_incomplete": (
        "Run the durable schema bootstrap or migration flow so all required execution and lineage tables exist "
        "before accepting traffic."
    ),
    "durable_metadata_readiness_timeout": (
        "The durable metadata readiness probe exceeded its configured time budget; inspect database latency, "
        "connectivity, and catalog responsiveness before accepting traffic."
    ),
    "lineage_storage_path_missing": (
        "Create or remount the configured lineage storage directory, then confirm the service is pointing at the "
        "expected path."
    ),
    "lineage_storage_path_invalid": (
        "Replace the configured lineage storage path with a writable directory path; the current path is not a directory."
    ),
    "lineage_storage_path_unreadable": (
        "Restore read, write, and traversal access to the configured lineage storage directory for the service account."
    ),
    "lineage_storage_write_probe_failed": (
        "Check free space, mount health, and write permissions on the lineage storage directory; the service could "
        "not complete a write/delete probe."
    ),
    "lineage_storage_readiness_timeout": (
        "The lineage storage readiness probe exceeded its configured time budget; inspect mount latency, write/fsync "
        "behavior, and filesystem health before accepting traffic."
    ),
    LINEAGE_STORAGE_CAPACITY_UNREADABLE_REASON: (
        "Inspect the lineage storage mount and filesystem health; the service could not read storage-capacity "
        "metrics needed for proactive saturation monitoring."
    ),
    "lineage_storage_free_bytes_below_threshold": (
        "Free space on the lineage storage filesystem is below the configured byte threshold; expand capacity or "
        "clear retained artifacts before lineage writes fail."
    ),
    "lineage_storage_free_ratio_below_threshold": (
        "Free capacity on the lineage storage filesystem is below the configured ratio threshold; expand capacity "
        "or clear retained artifacts before lineage writes fail."
    ),
}


def get_remediation_hint(reason: str | None) -> str | None:
    if reason is None:
        return None
    return _REMEDIATION_HINTS.get(reason)
