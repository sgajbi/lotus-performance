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


HistoryEntryStrings = dict[str, str | None]
HistoryManifestPayload = dict[str, Any]


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


def validate_history_entry_strings(
    entry: dict[str, Any],
    *,
    required_keys: tuple[str, ...],
    optional_keys: tuple[str, ...],
) -> HistoryEntryStrings | None:
    if any(not isinstance(entry.get(key), str) for key in required_keys):
        return None
    evidence_file_name = entry.get("evidence_file_name")
    if not isinstance(evidence_file_name, str) or not is_safe_evidence_file_name(evidence_file_name):
        return None
    if any(entry.get(key) is not None and not isinstance(entry.get(key), str) for key in optional_keys):
        return None
    return {
        **{key: entry[key] for key in required_keys},
        **{key: entry.get(key) for key in optional_keys},
    }


def build_history_manifest_payload(
    *,
    header: HistoryManifestHeader,
    entries: list[dict[str, Any]],
) -> HistoryManifestPayload:
    return {
        "latest_file_name": header.latest_file_name,
        "retained_file_names": header.retained_file_names,
        "retention_limit": header.retention_limit,
        "retention_max_age_days": header.retention_max_age_days,
        "entries": entries,
    }
