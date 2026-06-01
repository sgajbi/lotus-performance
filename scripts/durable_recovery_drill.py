from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, Callable, Coroutine
from uuid import UUID, uuid4

import pandas as pd
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if TYPE_CHECKING:
    from app.services.execution_registry import ExecutionRegistry
    from app.services.lineage_metadata_store import LineageMetadataStore

REQUIRED_TABLES = (
    "analytics_execution",
    "analytics_execution_stage",
    "analytics_upstream_snapshot",
    "analytics_compute_job",
    "analytics_async_result",
    "lineage_records",
    "lineage_payloads",
)

logger = logging.getLogger(__name__)


def _get_settings():
    from app.core.config import get_settings

    return get_settings()


class _DrillModel(BaseModel):
    key: str


class _ComputeDrillResponse(BaseModel):
    calculation_id: UUID
    status: str


@dataclass(frozen=True)
class RecoveryDrillEvidence:
    drill_name: str
    generated_at_utc: str
    evidence_file_name: str
    operator_id: str
    tenant_id: str | None
    correlation_id: str | None
    backup_identifier: str
    database_path: str
    restored_schema_mode: str
    owned_tables_present: list[str]
    compute_job_processed_count: int
    compute_async_result_status: str
    compute_execution_status: str
    processed_payload_count: int
    materialized_artifact_path: str
    materialized_artifact_exists: bool
    status: str


@dataclass(frozen=True)
class RecoveryDrillManifestEntry:
    evidence_file_name: str
    generated_at_utc: str
    operator_id: str
    tenant_id: str | None
    correlation_id: str | None
    backup_identifier: str
    status: str


@dataclass(frozen=True)
class RecoveryDrillManifest:
    latest_file_name: str
    retained_file_names: list[str]
    retention_limit: int
    retention_max_age_days: int
    entries: list[RecoveryDrillManifestEntry]


def run_recovery_drill(
    *,
    output_path: Path | None = None,
    output_dir: Path | None = None,
    operator_id: str = "unknown-operator",
    tenant_id: str | None = None,
    correlation_id: str | None = None,
    backup_identifier: str = "unknown-backup",
    retention_limit: int = 30,
    retention_max_age_days: int = 90,
) -> RecoveryDrillEvidence:
    normalized_operator_id = _normalize_required_evidence_identifier(operator_id, field_name="operator_id")
    normalized_tenant_id = _normalize_optional_evidence_identifier(tenant_id)
    normalized_correlation_id = _normalize_optional_evidence_identifier(correlation_id)
    normalized_backup_identifier = _normalize_required_evidence_identifier(
        backup_identifier,
        field_name="backup_identifier",
    )

    from app.models.returns_series import ReturnsSeriesRequest
    from app.services.async_result_store import AsyncResultStore
    from app.services.compute_job_store import ComputeJobStore
    from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
    from app.services.execution_registry import ExecutionRegistry
    from app.services.lineage_metadata_store import LineageMetadataStore
    from app.services.lineage_service import LineageService
    from app.workers.compute_executor_worker import _process_pending_jobs as process_pending_compute_jobs
    from app.workers.lineage_worker import process_pending_jobs

    with TemporaryDirectory(prefix="lotus-performance-recovery-drill-") as temp_dir:
        temp_path = Path(temp_dir)
        database_path = temp_path / "recovery-drill.db"
        execution_store = ExecutionRegistry(f"sqlite:///{database_path}")
        compute_store = ComputeJobStore(f"sqlite:///{database_path}")
        async_result_store = AsyncResultStore(f"sqlite:///{database_path}")
        lineage_store = LineageMetadataStore(f"sqlite:///{database_path}")

        try:
            _create_legacy_lineage_schema(lineage_store)
            bootstrap_durable_metadata_stores(
                execution_store=execution_store,
                compute_store=compute_store,
                async_result_store_=async_result_store,
                lineage_store=lineage_store,
            )

            _create_lineage_execution_stage(execution_store, calculation_id := uuid4())
            lineage_service = LineageService(
                storage_path=str(temp_path),
                metadata_store=lineage_store,
                execution_store=execution_store,
            )
            lineage_service.enqueue_capture(
                calculation_id=calculation_id,
                calculation_type="RecoveryDrill",
                request_model=_DrillModel(key="request"),
                response_model=_DrillModel(key="response"),
                calculation_details={"details.csv": pd.DataFrame([{"value": 1}])},
            )
            compute_calculation_id = uuid4()
            compute_request = ReturnsSeriesRequest.model_validate(
                {
                    "calculation_id": str(compute_calculation_id),
                    "portfolio_id": "RECOVERY_DRILL",
                    "as_of_date": "2026-02-25",
                    "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
                    "frequency": "DAILY",
                    "metric_basis": "NET",
                    "input_mode": "stateless",
                    "stateless_input": {
                        "portfolio_returns": [
                            {"date": "2026-02-23", "return_value": "0.01"},
                            {"date": "2026-02-24", "return_value": "0.02"},
                            {"date": "2026-02-25", "return_value": "0.03"},
                        ]
                    },
                }
            )
            execution_store.create_execution(
                calculation_id=compute_calculation_id,
                analytics_type="ReturnsSeries",
                portfolio_id="RECOVERY_DRILL",
                execution_mode="async",
                requested_window={"drill": "durable_metadata_restore_recovery"},
            )
            job_store = compute_store
            job_store.enqueue_job(
                calculation_id=compute_calculation_id,
                analytics_type="ReturnsSeries",
                request_payload=compute_request.model_dump(mode="json"),
            )
            execution_store.start_stage(compute_calculation_id, "execution")

            processed_payload_count = process_pending_jobs(
                limit=10,
                lineage_store=lineage_store,
                lineage_service_=lineage_service,
                execution_store=execution_store,
                worker_id="durable-recovery-drill",
                lease_seconds=60,
                max_attempts=3,
            )
            compute_job_processed_count = process_pending_compute_jobs(
                limit=10,
                job_store=job_store,
                execution_store=execution_store,
                result_store=async_result_store,
                worker_id="durable-recovery-drill",
                lease_seconds=60,
                returns_series_calculator=_build_compute_recovery_calculator(execution_store),
            )
            artifact_path = temp_path / str(calculation_id) / "details.csv"
            compute_result = async_result_store.get_result(compute_calculation_id)
            compute_execution = execution_store.get_execution(compute_calculation_id)
            generated_at_utc = datetime.now(UTC).isoformat()
            evidence = RecoveryDrillEvidence(
                drill_name="durable_metadata_restore_recovery",
                generated_at_utc=generated_at_utc,
                evidence_file_name=_build_evidence_file_name(generated_at_utc),
                operator_id=normalized_operator_id,
                tenant_id=normalized_tenant_id,
                correlation_id=normalized_correlation_id,
                backup_identifier=normalized_backup_identifier,
                database_path=str(database_path),
                restored_schema_mode="legacy_lineage_schema_upgraded_in_place",
                owned_tables_present=_fetch_owned_tables(lineage_store),
                compute_job_processed_count=compute_job_processed_count,
                compute_async_result_status=compute_result.result_status.value
                if compute_result is not None
                else "missing",
                compute_execution_status=compute_execution.status.value if compute_execution is not None else "missing",
                processed_payload_count=processed_payload_count,
                materialized_artifact_path=str(artifact_path),
                materialized_artifact_exists=artifact_path.exists(),
                status=(
                    "passed"
                    if (
                        processed_payload_count == 1
                        and artifact_path.exists()
                        and compute_job_processed_count == 1
                        and compute_result is not None
                        and compute_result.result_status.value == "complete"
                        and compute_execution is not None
                        and compute_execution.status.value == "complete"
                    )
                    else "failed"
                ),
            )

            if output_path is not None:
                _write_text_atomic(output_path, json.dumps(asdict(evidence), indent=2))
            if output_dir is not None:
                _persist_evidence_history(
                    output_dir=output_dir,
                    evidence=evidence,
                    retention_limit=retention_limit,
                    retention_max_age_days=retention_max_age_days,
                )

            return evidence
        finally:
            execution_store._engine.dispose()
            compute_store._engine.dispose()
            async_result_store._engine.dispose()
            lineage_store._engine.dispose()


def _normalize_required_evidence_identifier(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _normalize_optional_evidence_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _create_legacy_lineage_schema(lineage_store: "LineageMetadataStore") -> None:
    with lineage_store._engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE lineage_records (
                calculation_id VARCHAR(36) PRIMARY KEY,
                calculation_type VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                timestamp_utc DATETIME NOT NULL,
                artifact_names TEXT NOT NULL DEFAULT '',
                error_message TEXT
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE lineage_payloads (
                calculation_id VARCHAR(36) PRIMARY KEY,
                calculation_type VARCHAR(64) NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at_utc DATETIME NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def _create_lineage_execution_stage(execution_store: "ExecutionRegistry", calculation_id: UUID) -> None:
    execution_store.register_execution(
        calculation_id=calculation_id,
        analytics_type="RecoveryDrill",
        portfolio_id=None,
        execution_mode="async",
        requested_window={"drill": "durable_metadata_restore_recovery"},
    )
    execution_store.mark_running(calculation_id)
    execution_store.start_stage(calculation_id, "lineage_materialization")


def _build_compute_recovery_calculator(
    execution_store: "ExecutionRegistry",
) -> Callable[[BaseModel], Coroutine[object, object, _ComputeDrillResponse]]:
    async def _calculate(request: BaseModel) -> _ComputeDrillResponse:
        calculation_id = UUID(str(getattr(request, "calculation_id")))
        execution_store.complete_stage(
            calculation_id, "execution", details={"drill": "durable_metadata_restore_recovery"}
        )
        execution_store.mark_complete(calculation_id)
        return _ComputeDrillResponse(calculation_id=calculation_id, status="complete")

    return _calculate


def _fetch_owned_tables(lineage_store: "LineageMetadataStore") -> list[str]:
    with lineage_store._engine.begin() as connection:
        rows = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND (name LIKE 'analytics_%' OR name LIKE 'lineage_%')"
        ).fetchall()
    available = {row[0] for row in rows}
    return [table for table in REQUIRED_TABLES if table in available]


def _build_evidence_file_name(generated_at_utc: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z]+", "-", generated_at_utc).strip("-").lower()
    return f"{sanitized}.json"


def _persist_evidence_history(
    *,
    output_dir: Path,
    evidence: RecoveryDrillEvidence,
    retention_limit: int,
    retention_max_age_days: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(evidence), indent=2)
    _write_text_atomic(output_dir / evidence.evidence_file_name, payload)
    _write_text_atomic(output_dir / "latest.json", payload)
    _prune_historical_evidence(
        output_dir=output_dir,
        retention_limit=retention_limit,
        retention_max_age_days=retention_max_age_days,
    )
    _write_manifest(
        output_dir=output_dir,
        latest_file_name=evidence.evidence_file_name,
        retention_limit=retention_limit,
        retention_max_age_days=retention_max_age_days,
    )


def _prune_historical_evidence(*, output_dir: Path, retention_limit: int, retention_max_age_days: int) -> None:
    historical_files = sorted(
        path for path in output_dir.glob("*.json") if path.name not in {"latest.json", "manifest.json"}
    )
    fresh_files = _filter_fresh_history(
        historical_files=historical_files,
        retention_max_age_days=retention_max_age_days,
    )
    retained = fresh_files[-retention_limit:] if retention_limit > 0 else []
    retained_names = {path.name for path in retained}
    for path in historical_files:
        if path.name not in retained_names:
            path.unlink(missing_ok=True)


def _write_manifest(
    *, output_dir: Path, latest_file_name: str, retention_limit: int, retention_max_age_days: int
) -> None:
    entries: list[RecoveryDrillManifestEntry] = []
    for evidence_path in sorted(
        path for path in output_dir.glob("*.json") if path.name not in {"latest.json", "manifest.json"}
    ):
        entry = _load_manifest_entry(evidence_path)
        if entry is not None:
            entries.append(entry)
    manifest = RecoveryDrillManifest(
        latest_file_name=latest_file_name,
        retained_file_names=[entry.evidence_file_name for entry in entries],
        retention_limit=retention_limit,
        retention_max_age_days=retention_max_age_days,
        entries=entries,
    )
    _write_text_atomic(output_dir / "manifest.json", json.dumps(asdict(manifest), indent=2))


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=".recovery-drill-", suffix=".tmp", text=True)
    try:
        with open(fd, "w", encoding="utf-8", newline="", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.close(fd)
        Path(temp_path).replace(path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(temp_path).unlink(missing_ok=True)
        raise


def _filter_fresh_history(*, historical_files: list[Path], retention_max_age_days: int) -> list[Path]:
    if retention_max_age_days <= 0:
        return historical_files
    cutoff = datetime.now(UTC) - timedelta(days=retention_max_age_days)
    fresh_files: list[Path] = []
    for path in historical_files:
        try:
            payload = _read_recovery_drill_evidence_payload(path)
            generated_at = datetime.fromisoformat(payload["generated_at_utc"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.warning("Recovery drill evidence ignored during age pruning: %s", path, exc_info=True)
            continue
        if generated_at >= cutoff:
            fresh_files.append(path)
    return fresh_files


def _load_manifest_entry(path: Path) -> RecoveryDrillManifestEntry | None:
    try:
        payload = _read_recovery_drill_evidence_payload(path)
        return RecoveryDrillManifestEntry(
            evidence_file_name=_required_evidence_string(payload, "evidence_file_name"),
            generated_at_utc=_required_evidence_string(payload, "generated_at_utc"),
            operator_id=_required_evidence_string(payload, "operator_id"),
            tenant_id=_optional_evidence_string(payload, "tenant_id"),
            correlation_id=_optional_evidence_string(payload, "correlation_id"),
            backup_identifier=_required_evidence_string(payload, "backup_identifier"),
            status=_required_evidence_string(payload, "status"),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("Recovery drill evidence ignored during manifest rebuild: %s", path, exc_info=True)
        return None


def _required_evidence_string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a nonblank string")
    return value


def _optional_evidence_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string when present")
    return value


def _read_recovery_drill_evidence_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("recovery drill evidence payload must be an object")
    return payload


def main() -> int:
    settings = _get_settings()
    parser = argparse.ArgumentParser(
        description="Run the durable metadata recovery drill and emit structured evidence."
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional path for a JSON evidence artifact.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=settings.RECOVERY_DRILL_ARTIFACT_PATH,
        help="Directory for timestamped evidence history plus latest.json.",
    )
    parser.add_argument(
        "--retention-limit",
        type=int,
        default=settings.RECOVERY_DRILL_RETENTION_LIMIT,
        help="Maximum number of timestamped historical evidence files to retain.",
    )
    parser.add_argument(
        "--retention-max-age-days",
        type=int,
        default=settings.RECOVERY_DRILL_RETENTION_MAX_AGE_DAYS,
        help="Maximum age in days for retained historical recovery-drill evidence.",
    )
    parser.add_argument(
        "--operator-id", default="unknown-operator", help="Operator or automation identity for the drill."
    )
    parser.add_argument("--tenant-id", default=None, help="Optional enterprise tenant identity for the drill.")
    parser.add_argument(
        "--correlation-id",
        default=None,
        help="Optional enterprise correlation identifier for the drill.",
    )
    parser.add_argument(
        "--backup-identifier", default="unknown-backup", help="Backup or restore-set identifier used for the drill."
    )
    args = parser.parse_args()

    evidence = run_recovery_drill(
        output_path=args.output,
        output_dir=args.output_dir,
        operator_id=args.operator_id,
        tenant_id=args.tenant_id,
        correlation_id=args.correlation_id,
        backup_identifier=args.backup_identifier,
        retention_limit=args.retention_limit,
        retention_max_age_days=args.retention_max_age_days,
    )
    print(json.dumps(asdict(evidence), indent=2))
    return 0 if evidence.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
