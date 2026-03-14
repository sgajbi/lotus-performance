from uuid import uuid4

import pandas as pd
from pydantic import BaseModel

from app.services.async_result_store import AsyncResultStore
from app.services.compute_job_store import ComputeJobStore
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.execution_registry import ExecutionRegistry
from app.services.lineage_metadata_store import LineageMetadataStore
from app.services.lineage_service import LineageService
from app.workers import lineage_worker


class _Model(BaseModel):
    key: str


def test_bootstrap_durable_metadata_stores_calls_all_store_bootstraps(mocker):
    execution_store = mocker.Mock()
    compute_store = mocker.Mock()
    async_result_store_ = mocker.Mock()
    lineage_store = mocker.Mock()

    bootstrap_durable_metadata_stores(
        execution_store=execution_store,
        compute_store=compute_store,
        async_result_store_=async_result_store_,
        lineage_store=lineage_store,
    )

    execution_store.create_schema.assert_called_once_with()
    compute_store.create_schema.assert_called_once_with()
    async_result_store_.create_schema.assert_called_once_with()
    lineage_store.create_schema.assert_called_once_with()


def test_bootstrap_durable_metadata_stores_supports_recovery_drill_on_legacy_lineage_schema(monkeypatch, tmp_path):
    database_path = tmp_path / "recovery.db"
    execution_store = ExecutionRegistry(f"sqlite:///{database_path}")
    compute_store = ComputeJobStore(f"sqlite:///{database_path}")
    async_result_store_ = AsyncResultStore(f"sqlite:///{database_path}")
    lineage_store = LineageMetadataStore(f"sqlite:///{database_path}")

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

    bootstrap_durable_metadata_stores(
        execution_store=execution_store,
        compute_store=compute_store,
        async_result_store_=async_result_store_,
        lineage_store=lineage_store,
    )

    service = LineageService(storage_path=str(tmp_path), metadata_store=lineage_store)
    calculation_id = uuid4()
    service.enqueue_capture(
        calculation_id=calculation_id,
        calculation_type="TWR",
        request_model=_Model(key="request"),
        response_model=_Model(key="response"),
        calculation_details={"details.csv": pd.DataFrame([{"a": 1}])},
    )

    monkeypatch.setattr(lineage_worker, "lineage_metadata_store", lineage_store)
    monkeypatch.setattr(lineage_worker, "lineage_service", service)

    processed = lineage_worker.process_pending_jobs(limit=10)

    assert processed == 1
    assert (tmp_path / str(calculation_id) / "details.csv").exists()
    assert lineage_store.get_payload(calculation_id) is None
