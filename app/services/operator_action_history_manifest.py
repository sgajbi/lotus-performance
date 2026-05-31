from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.operator_action_evidence_paths import is_safe_evidence_file_name


@dataclass(frozen=True)
class HistoryManifestHeader:
    latest_file_name: str | None
    retained_file_names: list[str]
    retention_limit: int | None
    retention_max_age_days: int | None
    entries: list[Any]


def validate_history_manifest_header(payload: Any) -> HistoryManifestHeader | None:
    if not isinstance(payload, dict):
        return None

    latest_file_name = payload.get("latest_file_name")
    retained_file_names = payload.get("retained_file_names")
    retention_limit = payload.get("retention_limit")
    retention_max_age_days = payload.get("retention_max_age_days")
    entries = payload.get("entries")

    if latest_file_name is not None and (
        not isinstance(latest_file_name, str) or not is_safe_evidence_file_name(latest_file_name)
    ):
        return None
    if not isinstance(retained_file_names, list) or any(
        not isinstance(item, str) or not is_safe_evidence_file_name(item) for item in retained_file_names
    ):
        return None
    if retention_limit is not None and not isinstance(retention_limit, int):
        return None
    if retention_max_age_days is not None and not isinstance(retention_max_age_days, int):
        return None
    if not isinstance(entries, list):
        return None
    if latest_file_name is not None and latest_file_name not in retained_file_names:
        return None

    return HistoryManifestHeader(
        latest_file_name=latest_file_name,
        retained_file_names=list(retained_file_names),
        retention_limit=retention_limit,
        retention_max_age_days=retention_max_age_days,
        entries=entries,
    )
