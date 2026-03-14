from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import get_settings
from app.services.runtime_retention_service import (
    run_runtime_retention_cleanup,
)


@dataclass(frozen=True)
class RuntimeRetentionCleanupEvidence:
    cleanup_name: str
    generated_at_utc: str
    evidence_file_name: str
    operator_id: str
    tenant_id: str | None
    correlation_id: str | None
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
    tenant_id: str | None
    correlation_id: str | None
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


def execute_runtime_retention_cleanup(
    *,
    apply: bool,
    retention_days: int | None = None,
    operator_id: str,
    tenant_id: str | None = None,
    correlation_id: str | None = None,
    trigger_mode: str,
    job_id: str | None,
    output_dir: Path | None = None,
    retention_limit: int | None = None,
    retention_max_age_days: int | None = None,
) -> RuntimeRetentionCleanupEvidence:
    settings = get_settings()
    summary = run_runtime_retention_cleanup(
        retention_days=retention_days,
        dry_run=not apply,
    )
    generated_at_utc = datetime.now(UTC).isoformat()
    evidence = RuntimeRetentionCleanupEvidence(
        cleanup_name="runtime_retention_cleanup",
        generated_at_utc=generated_at_utc,
        evidence_file_name=_build_evidence_file_name(generated_at_utc),
        operator_id=operator_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        trigger_mode=trigger_mode,
        job_id=job_id,
        cleanup_mode="apply" if apply else "dry_run",
        status="applied" if apply else "planned",
        retention_days=summary.retention_days,
        cutoff_utc=summary.cutoff_utc,
        prunable_execution_count=summary.prunable_execution_count,
        prunable_compute_job_count=summary.prunable_compute_job_count,
        prunable_async_result_count=summary.prunable_async_result_count,
        prunable_lineage_record_count=summary.prunable_lineage_record_count,
        prunable_lineage_artifact_count=summary.prunable_lineage_artifact_count,
    )
    _persist_evidence_history(
        output_dir=output_dir or settings.RUNTIME_RETENTION_ARTIFACT_PATH,
        evidence=evidence,
        retention_limit=retention_limit if retention_limit is not None else settings.RUNTIME_RETENTION_HISTORY_LIMIT,
        retention_max_age_days=(
            retention_max_age_days
            if retention_max_age_days is not None
            else settings.RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS
        ),
    )
    return evidence


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
    latest_file_name = (
        evidence.evidence_file_name
        if evidence.evidence_file_name in retained_file_names
        else (retained_file_names[0] if retained_file_names else evidence.evidence_file_name)
    )
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
        tenant_id=None if payload.get("tenant_id") is None else str(payload["tenant_id"]),
        correlation_id=None if payload.get("correlation_id") is None else str(payload["correlation_id"]),
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
