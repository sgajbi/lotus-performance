from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.durable_store_json import read_json_file
from app.services.operator_action_evidence_paths import is_safe_evidence_file_name
from app.services.operator_action_evidence_strings import optional_evidence_string, required_evidence_string

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HistoryManifestHeader:
    latest_file_name: str | None
    retained_file_names: list[str]
    retention_limit: int | None
    retention_max_age_days: int | None
    entries: list[Any]


@dataclass(frozen=True)
class HistoryManifestReadReasons:
    directory_missing: str
    manifest_missing: str
    manifest_unreadable: str
    manifest_invalid: str


@dataclass(frozen=True)
class HistoryManifestReadResult:
    payload: Any
    reason: str | None = None


HistoryEntryStrings = dict[str, str | None]
HistoryManifestPayload = dict[str, Any]
HistoryEntryValidator = Callable[[Any], dict[str, Any] | None]


def read_history_manifest_payload(
    *,
    directory: Path,
    reasons: HistoryManifestReadReasons,
) -> HistoryManifestReadResult:
    manifest_path = directory / "manifest.json"
    if not directory.exists():
        return HistoryManifestReadResult(payload=None, reason=reasons.directory_missing)

    if not manifest_path.exists():
        return HistoryManifestReadResult(payload=None, reason=reasons.manifest_missing)

    try:
        payload = read_json_file(manifest_path)
    except OSError:
        logger.warning("Operator action history manifest unreadable at %s.", manifest_path, exc_info=True)
        return HistoryManifestReadResult(payload=None, reason=reasons.manifest_unreadable)
    except json.JSONDecodeError:
        logger.warning("Operator action history manifest invalid at %s.", manifest_path, exc_info=True)
        return HistoryManifestReadResult(payload=None, reason=reasons.manifest_invalid)

    return HistoryManifestReadResult(payload=payload)


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


def validate_history_manifest_payload(
    payload: Any,
    *,
    validate_entry: HistoryEntryValidator,
) -> HistoryManifestPayload | None:
    header = validate_history_manifest_header(payload)
    if header is None:
        return None

    validated_entries: list[dict[str, Any]] = []
    for entry in header.entries:
        validated_entry = validate_entry(entry)
        if validated_entry is None:
            return None
        validated_entries.append(validated_entry)

    return build_history_manifest_payload(header=header, entries=validated_entries)


def log_invalid_history_manifest_payload(*, manifest_path: Path, history_name: str) -> None:
    logger.warning("%s history manifest payload invalid at %s.", history_name, manifest_path)


def validate_history_entry_strings(
    entry: dict[str, Any],
    *,
    required_keys: tuple[str, ...],
    optional_keys: tuple[str, ...],
) -> HistoryEntryStrings | None:
    required_strings: dict[str, str] = {}
    for key in required_keys:
        try:
            required_strings[key] = required_evidence_string(entry, key)
        except (KeyError, ValueError):
            return None

    evidence_file_name = required_strings.get("evidence_file_name")
    if evidence_file_name is None or not is_safe_evidence_file_name(evidence_file_name):
        return None

    optional_strings: dict[str, str | None] = {}
    for key in optional_keys:
        try:
            optional_strings[key] = optional_evidence_string(entry, key)
        except ValueError:
            return None

    return {
        **required_strings,
        **optional_strings,
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
