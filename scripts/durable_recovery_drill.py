from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
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


class _DrillModel(BaseModel):
    key: str


@dataclass(frozen=True)
class RecoveryDrillEvidence:
    drill_name: str
    generated_at_utc: str
    database_path: str
    restored_schema_mode: str
    owned_tables_present: list[str]
    processed_payload_count: int
    materialized_artifact_path: str
    materialized_artifact_exists: bool
    status: str


def run_recovery_drill(*, output_path: Path | None = None) -> RecoveryDrillEvidence:
    from app.services.async_result_store import AsyncResultStore
    from app.services.compute_job_store import ComputeJobStore
    from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
    from app.services.execution_registry import ExecutionRegistry
    from app.services.lineage_metadata_store import LineageMetadataStore
    from app.services.lineage_service import LineageService
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

            processed_payload_count = process_pending_jobs(
                limit=10,
                lineage_store=lineage_store,
                lineage_service_=lineage_service,
                execution_store=execution_store,
                worker_id="durable-recovery-drill",
                lease_seconds=60,
                max_attempts=3,
            )
            artifact_path = temp_path / str(calculation_id) / "details.csv"
            evidence = RecoveryDrillEvidence(
                drill_name="durable_metadata_restore_recovery",
                generated_at_utc=datetime.now(UTC).isoformat(),
                database_path=str(database_path),
                restored_schema_mode="legacy_lineage_schema_upgraded_in_place",
                owned_tables_present=_fetch_owned_tables(lineage_store),
                processed_payload_count=processed_payload_count,
                materialized_artifact_path=str(artifact_path),
                materialized_artifact_exists=artifact_path.exists(),
                status="passed" if processed_payload_count == 1 and artifact_path.exists() else "failed",
            )

            if output_path is not None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(asdict(evidence), indent=2), encoding="utf-8")

            return evidence
        finally:
            execution_store._engine.dispose()
            compute_store._engine.dispose()
            async_result_store._engine.dispose()
            lineage_store._engine.dispose()


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


def _fetch_owned_tables(lineage_store: "LineageMetadataStore") -> list[str]:
    with lineage_store._engine.begin() as connection:
        rows = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND (name LIKE 'analytics_%' OR name LIKE 'lineage_%')"
        ).fetchall()
    available = {row[0] for row in rows}
    return [table for table in REQUIRED_TABLES if table in available]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the durable metadata recovery drill and emit structured evidence.")
    parser.add_argument("--output", type=Path, default=None, help="Optional path for a JSON evidence artifact.")
    args = parser.parse_args()

    evidence = run_recovery_drill(output_path=args.output)
    print(json.dumps(asdict(evidence), indent=2))
    return 0 if evidence.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
