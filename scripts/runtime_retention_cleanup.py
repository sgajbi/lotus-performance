from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import get_settings
from app.services.runtime_retention_service import run_runtime_retention_cleanup


@dataclass(frozen=True)
class RuntimeRetentionCleanupEvidence:
    cleanup_name: str
    generated_at_utc: str
    evidence_file_name: str
    operator_id: str
    trigger_mode: str
    job_id: str | None
    cleanup_mode: str
    status: str
    retention_days: int
    cutoff_utc: str
    prunable_execution_count: int
    prunable_compute_job_count: int
    prunable_async_result_count: int
    prunable_lineage_record_count: int
    prunable_lineage_artifact_count: int


@dataclass(frozen=True)
class RuntimeRetentionManifestEntry:
    evidence_file_name: str
    generated_at_utc: str
    operator_id: str
    trigger_mode: str
    job_id: str | None
    cleanup_mode: str
    status: str
    retention_days: int
    prunable_execution_count: int
    prunable_compute_job_count: int
    prunable_async_result_count: int
    prunable_lineage_record_count: int
    prunable_lineage_artifact_count: int


@dataclass(frozen=True)
class RuntimeRetentionManifest:
    latest_file_name: str
    retained_file_names: list[str]
    retention_limit: int
    retention_max_age_days: int
    entries: list[RuntimeRetentionManifestEntry]


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Prune retained lotus-performance runtime state and lineage artifacts.")
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
    summary = run_runtime_retention_cleanup(
        retention_days=args.retention_days,
        dry_run=not args.apply,
    )
    generated_at_utc = datetime.now(UTC).isoformat()
    evidence = RuntimeRetentionCleanupEvidence(
        cleanup_name="runtime_retention_cleanup",
        generated_at_utc=generated_at_utc,
        evidence_file_name=_build_evidence_file_name(generated_at_utc),
        operator_id=operator_id,
        trigger_mode=trigger_mode,
        job_id=job_id,
        cleanup_mode="apply" if args.apply else "dry_run",
        status="applied" if args.apply else "planned",
        retention_days=summary.retention_days,
        cutoff_utc=summary.cutoff_utc,
        prunable_execution_count=summary.prunable_execution_count,
        prunable_compute_job_count=summary.prunable_compute_job_count,
        prunable_async_result_count=summary.prunable_async_result_count,
        prunable_lineage_record_count=summary.prunable_lineage_record_count,
        prunable_lineage_artifact_count=summary.prunable_lineage_artifact_count,
    )
    _persist_evidence_history(
        output_dir=args.output_dir,
        evidence=evidence,
        retention_limit=args.retention_limit,
        retention_max_age_days=args.retention_max_age_days,
    )
    print(json.dumps(asdict(evidence), indent=2))


def _build_evidence_file_name(generated_at_utc: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z]+", "-", generated_at_utc).strip("-").lower()
    return f"{sanitized}.json"


def _persist_evidence_history(
    *,
    output_dir: Path,
    evidence: RuntimeRetentionCleanupEvidence,
    retention_limit: int,
    retention_max_age_days: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamped_path = output_dir / evidence.evidence_file_name
    payload = json.dumps(asdict(evidence), indent=2)
    _write_text_atomic(timestamped_path, payload)
    _write_text_atomic(output_dir / "latest.json", payload)

    _prune_old_evidence(output_dir=output_dir, retention_max_age_days=retention_max_age_days)

    retained_paths = sorted(
        (path for path in output_dir.glob("*.json") if path.name not in {"latest.json", "manifest.json"}),
        key=lambda path: path.name,
        reverse=True,
    )
    if retention_limit > 0 and len(retained_paths) > retention_limit:
        for stale_path in retained_paths[retention_limit:]:
            stale_path.unlink(missing_ok=True)
        retained_paths = retained_paths[:retention_limit]

    retained_file_names = [path.name for path in retained_paths]
    latest_file_name = evidence.evidence_file_name if evidence.evidence_file_name in retained_file_names else (retained_file_names[0] if retained_file_names else evidence.evidence_file_name)
    entries = [_load_manifest_entry(path) for path in retained_paths]
    manifest = RuntimeRetentionManifest(
        latest_file_name=latest_file_name,
        retained_file_names=retained_file_names,
        retention_limit=retention_limit,
        retention_max_age_days=retention_max_age_days,
        entries=entries,
    )
    _write_text_atomic(output_dir / "manifest.json", json.dumps(asdict(manifest), indent=2))


def _prune_old_evidence(*, output_dir: Path, retention_max_age_days: int) -> None:
    if retention_max_age_days <= 0:
        return
    cutoff = datetime.now(UTC) - timedelta(days=retention_max_age_days)
    for path in output_dir.glob("*.json"):
        if path.name in {"latest.json", "manifest.json"}:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            generated_at_utc = datetime.fromisoformat(str(payload["generated_at_utc"]).replace("Z", "+00:00"))
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            continue
        if generated_at_utc < cutoff:
            path.unlink(missing_ok=True)


def _load_manifest_entry(path: Path) -> RuntimeRetentionManifestEntry:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RuntimeRetentionManifestEntry(
        evidence_file_name=str(payload["evidence_file_name"]),
        generated_at_utc=str(payload["generated_at_utc"]),
        operator_id=str(payload["operator_id"]),
        trigger_mode=str(payload.get("trigger_mode", "manual")),
        job_id=None if payload.get("job_id") is None else str(payload["job_id"]),
        cleanup_mode=str(payload["cleanup_mode"]),
        status=str(payload["status"]),
        retention_days=int(payload["retention_days"]),
        prunable_execution_count=int(payload["prunable_execution_count"]),
        prunable_compute_job_count=int(payload["prunable_compute_job_count"]),
        prunable_async_result_count=int(payload["prunable_async_result_count"]),
        prunable_lineage_record_count=int(payload["prunable_lineage_record_count"]),
        prunable_lineage_artifact_count=int(payload["prunable_lineage_artifact_count"]),
    )


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
