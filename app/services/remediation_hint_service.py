from __future__ import annotations

_REMEDIATION_HINTS: dict[str, str] = {
    "durable_metadata_store_unreachable": (
        "Verify the durable metadata database is reachable from the service and that the configured "
        "database URL, credentials, and network path are correct."
    ),
    "durable_metadata_schema_incomplete": (
        "Run the durable schema bootstrap or migration flow so all required execution and lineage tables exist "
        "before accepting traffic."
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
}


def get_remediation_hint(reason: str | None) -> str | None:
    if reason is None:
        return None
    return _REMEDIATION_HINTS.get(reason)
