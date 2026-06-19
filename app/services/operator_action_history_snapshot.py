from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from app.services.operator_action_history_manifest import HistoryManifestPayload

SnapshotT = TypeVar("SnapshotT")


def build_available_history_snapshot(
    snapshot_type: Callable[..., SnapshotT],
    *,
    directory: Path,
    manifest_payload: HistoryManifestPayload,
    entries: list[Any],
    total_entries: int,
    matched_entries: int,
    returned_entries: int,
    next_offset: int | None,
    applied_filters: dict[str, str | int],
) -> SnapshotT:
    return snapshot_type(
        status="available",
        artifact_directory=str(directory),
        latest_file_name=manifest_payload["latest_file_name"],
        retained_file_names=manifest_payload["retained_file_names"],
        retention_limit=manifest_payload["retention_limit"],
        retention_max_age_days=manifest_payload["retention_max_age_days"],
        entries=entries,
        total_entries=total_entries,
        matched_entries=matched_entries,
        returned_entries=returned_entries,
        next_offset=next_offset,
        applied_filters=applied_filters,
        reason=None,
    )


def build_unavailable_history_snapshot(
    snapshot_type: Callable[..., SnapshotT],
    *,
    directory: Path,
    applied_filters: dict[str, str | int],
    reason: str,
) -> SnapshotT:
    return snapshot_type(
        status="unavailable",
        artifact_directory=str(directory),
        latest_file_name=None,
        retained_file_names=[],
        retention_limit=None,
        retention_max_age_days=None,
        entries=[],
        total_entries=0,
        matched_entries=0,
        returned_entries=0,
        next_offset=None,
        applied_filters=applied_filters,
        reason=reason,
    )
