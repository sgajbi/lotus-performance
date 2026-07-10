from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.durable_store_json import read_json_object_file


@dataclass(frozen=True)
class RuntimeRetentionLegalHold:
    calculation_id: str
    reason_code: str
    source: str | None = None


@dataclass(frozen=True)
class RuntimeRetentionLegalHoldIndex:
    holds_by_calculation_id: dict[str, RuntimeRetentionLegalHold]

    def protected_ids_for(self, calculation_ids: list[str]) -> list[str]:
        return sorted(
            calculation_id for calculation_id in calculation_ids if calculation_id in self.holds_by_calculation_id
        )

    def reason_counts_for(self, calculation_ids: list[str]) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for calculation_id in calculation_ids:
            hold = self.holds_by_calculation_id.get(calculation_id)
            if hold is not None:
                counter[hold.reason_code] += 1
        return dict(sorted(counter.items()))


def load_runtime_retention_legal_hold_index(path: Path | None = None) -> RuntimeRetentionLegalHoldIndex:
    hold_path = path or get_settings().RUNTIME_RETENTION_LEGAL_HOLD_PATH
    if not hold_path.exists():
        return RuntimeRetentionLegalHoldIndex(holds_by_calculation_id={})
    payload = read_json_object_file(
        hold_path, object_error_message="runtime retention legal hold payload must be an object"
    )
    return RuntimeRetentionLegalHoldIndex(
        holds_by_calculation_id={
            hold.calculation_id: hold for hold in _runtime_retention_legal_holds_from_payload(payload)
        }
    )


def _runtime_retention_legal_holds_from_payload(payload: dict[str, Any]) -> list[RuntimeRetentionLegalHold]:
    raw_holds = payload.get("holds")
    if not isinstance(raw_holds, list):
        raise ValueError("runtime retention legal hold payload must contain a holds list")
    return [_runtime_retention_legal_hold_from_payload(raw_hold) for raw_hold in raw_holds]


def _runtime_retention_legal_hold_from_payload(payload: Any) -> RuntimeRetentionLegalHold:
    if not isinstance(payload, dict):
        raise ValueError("runtime retention legal hold entries must be objects")
    calculation_id = _required_hold_string(payload, "calculation_id")
    reason_code = _required_hold_string(payload, "reason_code")
    source = _optional_hold_string(payload.get("source"))
    return RuntimeRetentionLegalHold(calculation_id=calculation_id, reason_code=reason_code, source=source)


def _required_hold_string(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    normalized = _optional_hold_string(value)
    if normalized is None:
        raise ValueError(f"runtime retention legal hold {field_name} must be a nonblank string")
    return normalized


def _optional_hold_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("runtime retention legal hold string fields must be strings")
    normalized = value.strip()
    return normalized or None


def write_runtime_retention_legal_hold_template(path: Path) -> None:
    payload = {
        "holds": [
            {
                "calculation_id": "replace-with-calculation-id",
                "reason_code": "client_dispute",
                "source": "ticket-or-approval-reference",
            }
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
