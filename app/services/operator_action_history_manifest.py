from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.durable_store_json import read_json_file
from app.services.operator_action_evidence_paths import is_safe_evidence_file_name
from app.services.operator_action_evidence_strings import (
    optional_evidence_int_fields_valid,
    optional_evidence_string,
    required_evidence_string,
)
from app.services.runtime_status_time import parse_utc_datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HistoryManifestHeader:
    latest_file_name: str | None
    retained_file_names: list[str]
    retention_limit: int | None
    retention_max_age_days: int | None
    entries: list[Any]


@dataclass(frozen=True)
class _HistoryManifestFileNames:
    latest_file_name: str | None
    retained_file_names: list[str]


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


def _safe_manifest_file_name(value: Any, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not is_safe_evidence_file_name(value):
        return None
    return value


def _safe_retained_manifest_file_names(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None

    retained_file_names: list[str] = []
    for item in value:
        safe_item = _safe_manifest_file_name(item)
        if safe_item is None:
            return None
        retained_file_names.append(safe_item)
    return retained_file_names


def _manifest_retention_fields(payload: dict[str, Any]) -> tuple[int | None, int | None] | None:
    if not optional_evidence_int_fields_valid(payload, ("retention_limit", "retention_max_age_days")):
        return None
    return payload.get("retention_limit"), payload.get("retention_max_age_days")


def _history_manifest_file_names(payload: dict[str, Any]) -> _HistoryManifestFileNames | None:
    latest_file_name = payload.get("latest_file_name")
    retained_file_names = payload.get("retained_file_names")

    safe_latest_file_name = _safe_manifest_file_name(latest_file_name, allow_none=True)
    if latest_file_name is not None and safe_latest_file_name is None:
        return None
    safe_retained_file_names = _safe_retained_manifest_file_names(retained_file_names)
    if safe_retained_file_names is None:
        return None
    if safe_latest_file_name is not None and safe_latest_file_name not in safe_retained_file_names:
        return None
    return _HistoryManifestFileNames(
        latest_file_name=safe_latest_file_name,
        retained_file_names=safe_retained_file_names,
    )


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

    entries = payload.get("entries")

    file_names = _history_manifest_file_names(payload)
    if file_names is None:
        return None
    retention_fields = _manifest_retention_fields(payload)
    if retention_fields is None:
        return None
    if not isinstance(entries, list):
        return None

    retention_limit, retention_max_age_days = retention_fields
    return HistoryManifestHeader(
        latest_file_name=file_names.latest_file_name,
        retained_file_names=file_names.retained_file_names,
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


def validate_history_entry_generated_at_utc(entry_strings: HistoryEntryStrings) -> str | None:
    generated_at_utc = entry_strings.get("generated_at_utc")
    if not isinstance(generated_at_utc, str):
        return None
    try:
        parse_utc_datetime(generated_at_utc)
    except ValueError:
        return None
    return generated_at_utc


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
