from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, inspect

from scripts.durable_schema_apply import BOOTSTRAP_STORES, apply_durable_schema, main


def _create_legacy_lineage_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
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
    finally:
        engine.dispose()


def _create_legacy_composite_fact_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE composite_member_return_facts (
                    fact_key VARCHAR(360) PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    composite_id VARCHAR(128) NOT NULL,
                    portfolio_id VARCHAR(128) NOT NULL,
                    period_start DATE NOT NULL,
                    period_end DATE NOT NULL,
                    return_value TEXT NOT NULL,
                    beginning_market_value TEXT NOT NULL,
                    ending_market_value TEXT NOT NULL,
                    reporting_currency VARCHAR(3) NOT NULL,
                    calculation_id VARCHAR(64) NOT NULL,
                    source_snapshot_id VARCHAR(256) NOT NULL,
                    status VARCHAR(64) NOT NULL,
                    reason_codes_json TEXT NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO composite_member_return_facts (
                    fact_key, tenant_id, composite_id, portfolio_id, period_start, period_end,
                    return_value, beginning_market_value, ending_market_value,
                    reporting_currency, calculation_id, source_snapshot_id, status,
                    reason_codes_json
                ) VALUES (
                    'legacy-fact-key', 'tenant-a', 'PB_GLOBAL_BALANCED_USD', 'P1',
                    '2026-01-01', '2026-01-31', '0.01', '100.00', '101.00',
                    'USD', 'legacy-calculation', 'legacy-snapshot', 'READY', '[]'
                )
                """
            )
    finally:
        engine.dispose()


def _create_publication_schema_without_lineage_columns(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE composite_member_return_fact_publications (
                    publication_key VARCHAR(80) PRIMARY KEY,
                    composite_id VARCHAR(128) NOT NULL,
                    return_view VARCHAR(32) NOT NULL,
                    reporting_currency VARCHAR(3) NOT NULL,
                    restatement_sequence INTEGER NOT NULL,
                    period_start DATE NOT NULL,
                    period_end DATE NOT NULL
                )
                """
            )
    finally:
        engine.dispose()


def _columns(database_url: str, table_name: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        return {column["name"] for column in inspect(engine).get_columns(table_name)}
    finally:
        engine.dispose()


def test_apply_durable_schema_refuses_populated_partial_composite_identity(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    _create_legacy_lineage_schema(database_url)
    _create_legacy_composite_fact_schema(database_url)

    evidence = apply_durable_schema(database_url=database_url)

    assert evidence.status == "failed"
    assert evidence.bootstrap_error is not None
    assert "Partial composite schema records cannot be assigned automatically" in evidence.bootstrap_error
    assert {"worker_id", "leased_at_utc", "lease_expires_at_utc"} <= _columns(database_url, "lineage_payloads")
    assert "return_view" not in _columns(database_url, "composite_member_return_facts")
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            retained_row = connection.exec_driver_sql(
                "SELECT fact_key, tenant_id, composite_id FROM composite_member_return_facts "
                "WHERE calculation_id = 'legacy-calculation'"
            ).one()
    finally:
        engine.dispose()
    assert retained_row == ("legacy-fact-key", "tenant-a", "PB_GLOBAL_BALANCED_USD")


def test_apply_durable_schema_rebuilds_empty_publication_without_lineage_columns(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'malformed-publication.db'}"
    output_dir = tmp_path / "evidence"
    _create_publication_schema_without_lineage_columns(database_url)

    evidence = apply_durable_schema(database_url=database_url)

    publication_check = next(
        check
        for check in evidence.additive_upgrade_checks
        if check.table_name == "composite_member_return_fact_publications"
    )
    assert evidence.status == "passed"
    assert evidence.bootstrap_error is None
    assert publication_check.status == "passed"
    assert publication_check.missing_columns == []
    assert main(["--database-url", database_url, "--output-dir", str(output_dir)]) == 0
    latest_payload = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["status"] == "passed"
    assert latest_payload["bootstrap_error"] is None
    assert latest_payload["additive_upgrade_checks"][-1]["missing_columns"] == []


def test_durable_schema_apply_main_writes_operator_evidence(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    output_dir = tmp_path / "evidence"

    exit_code = main(["--database-url", database_url, "--output-dir", str(output_dir)])

    assert exit_code == 0
    latest_payload = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["operation"] == "durable_schema_bootstrap_apply_verify"
    assert latest_payload["status"] == "passed"
    assert latest_payload["missing_owned_tables"] == []
    assert latest_payload["schema_version"] == "lotus-performance-durable-schema-apply.v2"
    assert [check["store_name"] for check in latest_payload["schema_verification_checks"]] == list(BOOTSTRAP_STORES)
    assert all(
        check["status"] == "passed" and check["issues"] == [] for check in latest_payload["schema_verification_checks"]
    )


def test_owner_evidence_refuses_existing_same_named_incompatible_index(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'incompatible-index.db'}"
    assert apply_durable_schema(database_url=database_url).status == "passed"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX ix_lineage_payloads_created_at")
            connection.exec_driver_sql(
                "CREATE INDEX ix_lineage_payloads_created_at ON lineage_payloads (attempt_count)"
            )
    finally:
        engine.dispose()
    evidence = apply_durable_schema(database_url=database_url)
    assert evidence.status == "failed"
    assert evidence.bootstrap_error is None
    checks = {check.store_name: check for check in evidence.schema_verification_checks}
    assert checks["LineageMetadataStore"].status == "failed"
    assert "index:lineage_payloads.ix_lineage_payloads_created_at" in checks["LineageMetadataStore"].issues
    assert main(["--database-url", database_url, "--output-dir", str(tmp_path / "evidence")]) == 1
