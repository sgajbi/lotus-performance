from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, inspect

from scripts.durable_schema_apply import apply_durable_schema, main


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
    finally:
        engine.dispose()


def _columns(database_url: str, table_name: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        return {column["name"] for column in inspect(engine).get_columns(table_name)}
    finally:
        engine.dispose()


def test_apply_durable_schema_bootstraps_owned_tables_and_additive_columns(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    _create_legacy_lineage_schema(database_url)
    _create_legacy_composite_fact_schema(database_url)

    evidence = apply_durable_schema(database_url=database_url)

    assert evidence.status == "passed"
    assert evidence.missing_owned_tables == []
    assert "analytics_execution" in evidence.owned_tables_present
    assert "composite_member_return_facts" in evidence.owned_tables_present
    assert all(check.status == "passed" for check in evidence.additive_upgrade_checks)
    assert {"worker_id", "leased_at_utc", "lease_expires_at_utc"} <= _columns(database_url, "lineage_payloads")
    assert {"return_view", "source_fingerprint", "restatement_version"} <= _columns(
        database_url,
        "composite_member_return_facts",
    )


def test_durable_schema_apply_main_writes_operator_evidence(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    output_dir = tmp_path / "evidence"

    exit_code = main(["--database-url", database_url, "--output-dir", str(output_dir)])

    assert exit_code == 0
    latest_payload = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["operation"] == "durable_schema_bootstrap_apply_verify"
    assert latest_payload["status"] == "passed"
    assert latest_payload["missing_owned_tables"] == []
