import json

import pytest

from app.services.runtime_retention_legal_hold import (
    RuntimeRetentionLegalHoldIndex,
    load_runtime_retention_legal_hold_index,
    write_runtime_retention_legal_hold_template,
)


def test_runtime_retention_legal_hold_index_loads_protected_ids_and_reason_counts(tmp_path) -> None:
    hold_path = tmp_path / "legal-holds.json"
    hold_path.write_text(
        json.dumps(
            {
                "holds": [
                    {
                        "calculation_id": " calc-a ",
                        "reason_code": " client_dispute ",
                        "source": " case-1 ",
                    },
                    {
                        "calculation_id": "calc-b",
                        "reason_code": "investigation",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    index = load_runtime_retention_legal_hold_index(hold_path)

    assert index.protected_ids_for(["calc-a", "calc-b", "calc-c"]) == ["calc-a", "calc-b"]
    assert index.reason_counts_for(["calc-a", "calc-b", "calc-c"]) == {
        "client_dispute": 1,
        "investigation": 1,
    }
    assert index.holds_by_calculation_id["calc-a"].source == "case-1"


def test_runtime_retention_legal_hold_index_is_empty_when_source_file_is_absent(tmp_path) -> None:
    index = load_runtime_retention_legal_hold_index(tmp_path / "missing.json")

    assert index == RuntimeRetentionLegalHoldIndex(holds_by_calculation_id={})


def test_runtime_retention_legal_hold_index_rejects_invalid_entries(tmp_path) -> None:
    hold_path = tmp_path / "legal-holds.json"
    hold_path.write_text('{"holds":[{"calculation_id":"calc-a","reason_code":"   "}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="reason_code must be a nonblank string"):
        load_runtime_retention_legal_hold_index(hold_path)


def test_write_runtime_retention_legal_hold_template_writes_reviewable_source(tmp_path) -> None:
    hold_path = tmp_path / "runtime-retention-holds" / "legal-holds.json"

    write_runtime_retention_legal_hold_template(hold_path)

    payload = json.loads(hold_path.read_text(encoding="utf-8"))
    assert payload["holds"][0]["reason_code"] == "client_dispute"
    assert payload["holds"][0]["source"] == "ticket-or-approval-reference"
