from __future__ import annotations

import argparse
from pathlib import Path

REQUIRED_DOC = Path("docs/standards/migration-contract.md")
REQUIRED_PHRASES_BY_MODE = {
    "durable-schema": (
        "durable metadata schema",
        "forward-only",
        "additive upgrade",
        "rollback runbook",
        "versioned migration",
    )
}


def validate_migration_contract(*, mode: str, document_path: Path = REQUIRED_DOC) -> tuple[bool, list[str] | None]:
    if not document_path.exists():
        return False, [f"Missing required migration contract document: {document_path}"]

    content = document_path.read_text(encoding="utf-8").lower()
    missing = [phrase for phrase in REQUIRED_PHRASES_BY_MODE[mode] if phrase not in content]
    if missing:
        return False, missing
    return True, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate migration contract requirements.")
    parser.add_argument("--mode", choices=tuple(REQUIRED_PHRASES_BY_MODE), default="durable-schema")
    args = parser.parse_args()

    valid, errors = validate_migration_contract(mode=args.mode)
    if not valid:
        if errors and errors[0].startswith("Missing required migration contract document:"):
            print(errors[0])
            return 1
        print("Migration contract document is missing required phrases:")
        for phrase in errors or []:
            print(f"- {phrase}")
        return 1

    print(f"Migration contract check passed ({args.mode} mode).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
