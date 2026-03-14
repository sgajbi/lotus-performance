from __future__ import annotations

from pathlib import Path

REQUIRED_DOC = Path("docs/runbooks/durable-metadata-recovery.md")
REQUIRED_PHRASES = (
    "backup and restore order",
    "worker restart order",
    "performance-analytics",
    "performance-compute-executor",
    "performance-lineage-worker",
    "analytics_execution",
    "analytics_compute_job",
    "lineage_payloads",
    "scripts/durable_recovery_drill.py",
    "structured recovery evidence json",
    "/health/ready",
    "/integration/runtime-status",
    "forward-only",
)


def validate_durable_recovery_runbook(*, document_path: Path = REQUIRED_DOC) -> tuple[bool, list[str] | None]:
    if not document_path.exists():
        return False, [f"Missing required durable recovery runbook: {document_path}"]

    content = document_path.read_text(encoding="utf-8").lower()
    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in content]
    if missing:
        return False, missing
    return True, None


def main() -> int:
    valid, errors = validate_durable_recovery_runbook()
    if not valid:
        if errors and errors[0].startswith("Missing required durable recovery runbook:"):
            print(errors[0])
            return 1
        print("Durable recovery runbook is missing required phrases:")
        for phrase in errors or []:
            print(f"- {phrase}")
        return 1

    print("Durable recovery runbook check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
