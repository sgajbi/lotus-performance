import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.core.config import get_settings
from app.services.runtime_retention_execution_service import (
    RuntimeRetentionCleanupEvidence,
    RuntimeRetentionManifest,
    RuntimeRetentionManifestEntry,
    _build_evidence_file_name,
    _load_manifest_entry,
    _persist_evidence_history,
    _prune_old_evidence,
    _write_text_atomic,
    execute_runtime_retention_cleanup,
)

__all__ = [
    "RuntimeRetentionCleanupEvidence",
    "RuntimeRetentionManifest",
    "RuntimeRetentionManifestEntry",
    "_build_evidence_file_name",
    "_load_manifest_entry",
    "_persist_evidence_history",
    "_prune_old_evidence",
    "_write_text_atomic",
    "execute_runtime_retention_cleanup",
    "main",
]


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Prune retained lotus-performance runtime state and lineage artifacts."
    )
    parser.add_argument("--retention-days", type=int, default=None, help="Override runtime retention window in days.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions. Without this flag the command runs in dry-run mode.",
    )
    parser.add_argument(
        "--operator-id",
        default="unknown-operator",
        help="Operator or automation identity recorded in retained cleanup evidence.",
    )
    parser.add_argument(
        "--trigger-mode",
        choices=("manual", "scheduled"),
        default="manual",
        help="Execution trigger recorded in retained cleanup evidence.",
    )
    parser.add_argument(
        "--job-id",
        default=None,
        help="Optional scheduler or automation job identity recorded in retained cleanup evidence.",
    )
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="Run with the configured scheduled automation identity and trigger mode.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=settings.RUNTIME_RETENTION_ARTIFACT_PATH,
        help="Directory for timestamped cleanup evidence history plus latest.json.",
    )
    parser.add_argument(
        "--retention-limit",
        type=int,
        default=settings.RUNTIME_RETENTION_HISTORY_LIMIT,
        help="Maximum number of retained timestamped cleanup evidence files.",
    )
    parser.add_argument(
        "--retention-max-age-days",
        type=int,
        default=settings.RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS,
        help="Maximum age in days for retained cleanup evidence files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    operator_id = args.operator_id
    trigger_mode = args.trigger_mode
    job_id = args.job_id
    if args.scheduled:
        operator_id = settings.RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID
        trigger_mode = "scheduled"
        job_id = job_id or settings.RUNTIME_RETENTION_AUTOMATION_JOB_ID
    evidence = execute_runtime_retention_cleanup(
        apply=args.apply,
        retention_days=args.retention_days,
        operator_id=operator_id,
        trigger_mode=trigger_mode,
        job_id=job_id,
        output_dir=args.output_dir,
        retention_limit=args.retention_limit,
        retention_max_age_days=args.retention_max_age_days,
    )
    print(json.dumps(asdict(evidence), indent=2))


if __name__ == "__main__":
    main()
