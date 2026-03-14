from __future__ import annotations

from pathlib import Path

REQUIRED_DOC = Path("docs/standards/durable-schema-inventory.md")
REQUIRED_PHRASES = (
    "analytics_execution",
    "analytics_execution_stage",
    "analytics_upstream_snapshot",
    "analytics_compute_job",
    "analytics_async_result",
    "lineage_records",
    "lineage_payloads",
    "additive upgrade",
    "rollback runbook",
    "backup and restore",
)


def validate_durable_schema_inventory(*, document_path: Path = REQUIRED_DOC) -> tuple[bool, list[str] | None]:
    if not document_path.exists():
        return False, [f"Missing required durable schema inventory document: {document_path}"]

    content = document_path.read_text(encoding="utf-8").lower()
    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in content]
    if missing:
        return False, missing
    return True, None


def main() -> int:
    valid, errors = validate_durable_schema_inventory()
    if not valid:
        if errors and errors[0].startswith("Missing required durable schema inventory document:"):
            print(errors[0])
            return 1
        print("Durable schema inventory document is missing required phrases:")
        for phrase in errors or []:
            print(f"- {phrase}")
        return 1

    print("Durable schema inventory check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
