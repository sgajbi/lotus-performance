from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from sqlalchemy import inspect
from sqlalchemy.engine import Engine, make_url

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OWNED_DURABLE_TABLES = (
    "analytics_execution",
    "analytics_execution_stage",
    "analytics_upstream_snapshot",
    "analytics_compute_job",
    "analytics_async_result",
    "lineage_records",
    "lineage_payloads",
    "composite_definitions",
    "composite_memberships",
    "composite_member_return_facts",
)
ADDITIVE_COLUMN_CHECKS = {
    "lineage_payloads": (
        "worker_id",
        "leased_at_utc",
        "lease_expires_at_utc",
    ),
    "composite_member_return_facts": (
        "return_view",
        "source_fingerprint",
        "restatement_version",
    ),
}
BOOTSTRAP_STORES = (
    "ExecutionRegistry",
    "ComputeJobStore",
    "AsyncResultStore",
    "LineageMetadataStore",
    "CompositeMetadataStore",
)


@dataclass(frozen=True)
class DurableSchemaColumnCheck:
    table_name: str
    required_columns: list[str]
    present_columns: list[str]
    missing_columns: list[str]
    status: str


@dataclass(frozen=True)
class DurableSchemaApplyEvidence:
    schema_version: str
    generated_at_utc: str
    operation: str
    database_url: str
    bootstrap_stores: list[str]
    owned_tables_present: list[str]
    missing_owned_tables: list[str]
    additive_upgrade_checks: list[DurableSchemaColumnCheck]
    status: str


def apply_durable_schema(*, database_url: str | None = None) -> DurableSchemaApplyEvidence:
    from app.core.config import get_settings
    from app.services.async_result_store import AsyncResultStore
    from app.services.composite_metadata_store import CompositeMetadataStore
    from app.services.compute_job_store import ComputeJobStore
    from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
    from app.services.execution_registry import ExecutionRegistry
    from app.services.lineage_metadata_store import LineageMetadataStore

    active_database_url = database_url or get_settings().LINEAGE_METADATA_DATABASE_URL
    execution_store = ExecutionRegistry(active_database_url)
    compute_store = ComputeJobStore(active_database_url)
    async_result_store = AsyncResultStore(active_database_url)
    lineage_store = LineageMetadataStore(active_database_url)
    composite_store = CompositeMetadataStore(active_database_url)
    stores = (execution_store, compute_store, async_result_store, lineage_store, composite_store)

    try:
        bootstrap_durable_metadata_stores(
            execution_store=execution_store,
            compute_store=compute_store,
            async_result_store_=async_result_store,
            lineage_store=lineage_store,
            composite_store=composite_store,
        )
        return _build_evidence(database_url=active_database_url, engine=execution_store._engine)
    finally:
        for store in stores:
            store._engine.dispose()


def _build_evidence(*, database_url: str, engine: Engine) -> DurableSchemaApplyEvidence:
    available_tables = set(inspect(engine).get_table_names())
    owned_tables_present = [table_name for table_name in OWNED_DURABLE_TABLES if table_name in available_tables]
    missing_owned_tables = [table_name for table_name in OWNED_DURABLE_TABLES if table_name not in available_tables]
    additive_upgrade_checks = _build_additive_column_checks(engine=engine, available_tables=available_tables)
    status = (
        "passed"
        if not missing_owned_tables and all(not check.missing_columns for check in additive_upgrade_checks)
        else "failed"
    )
    return DurableSchemaApplyEvidence(
        schema_version="lotus-performance-durable-schema-apply.v1",
        generated_at_utc=datetime.now(UTC).isoformat(),
        operation="durable_schema_bootstrap_apply_verify",
        database_url=_safe_database_url(database_url),
        bootstrap_stores=list(BOOTSTRAP_STORES),
        owned_tables_present=owned_tables_present,
        missing_owned_tables=missing_owned_tables,
        additive_upgrade_checks=additive_upgrade_checks,
        status=status,
    )


def _build_additive_column_checks(*, engine: Engine, available_tables: set[str]) -> list[DurableSchemaColumnCheck]:
    inspector = inspect(engine)
    checks: list[DurableSchemaColumnCheck] = []
    for table_name, required_columns_tuple in ADDITIVE_COLUMN_CHECKS.items():
        required_columns = list(required_columns_tuple)
        present_columns: list[str] = []
        if table_name in available_tables:
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            present_columns = [column_name for column_name in required_columns if column_name in columns]
        missing_columns = [column_name for column_name in required_columns if column_name not in present_columns]
        checks.append(
            DurableSchemaColumnCheck(
                table_name=table_name,
                required_columns=required_columns,
                present_columns=present_columns,
                missing_columns=missing_columns,
                status="passed" if not missing_columns else "failed",
            )
        )
    return checks


def _safe_database_url(database_url: str) -> str:
    return make_url(database_url).render_as_string(hide_password=True)


def _persist_evidence(
    evidence: DurableSchemaApplyEvidence, *, output_dir: Path | None, output_path: Path | None
) -> None:
    payload = json.dumps(asdict(evidence), indent=2)
    if output_path is not None:
        _write_text_atomic(output_path, payload)
    if output_dir is not None:
        evidence_file = _evidence_file_name(evidence.generated_at_utc)
        _write_text_atomic(output_dir / evidence_file, payload)
        _write_text_atomic(output_dir / "latest.json", payload)


def _evidence_file_name(generated_at_utc: str) -> str:
    sanitized = "".join(character if character.isalnum() else "-" for character in generated_at_utc).strip("-").lower()
    return f"{sanitized}.json"


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=".durable-schema-apply-", suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
        Path(temp_path).replace(path)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply and verify the lotus-performance durable metadata schema bootstrap."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional SQLAlchemy database URL. Defaults to LINEAGE_METADATA_DATABASE_URL.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/durable-schema-apply"),
        help="Directory for timestamped durable schema apply evidence and latest.json.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional explicit JSON evidence path.")
    args = parser.parse_args(argv)

    evidence = apply_durable_schema(database_url=args.database_url)
    _persist_evidence(evidence, output_dir=args.output_dir, output_path=args.output)
    print(json.dumps(asdict(evidence), indent=2))
    return 0 if evidence.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
