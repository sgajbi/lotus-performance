from uuid import uuid4

import pandas as pd
import pytest
from pydantic import BaseModel
from sqlalchemy import event, inspect

from app.adapters.durable_schema.catalog import require_metadata_schema
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.services.async_result_store import AsyncResultStore
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.compute_job_store import ComputeJobStore
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.execution_registry import ExecutionRegistry
from app.services.lineage_metadata_store import Base as LineageBase
from app.services.lineage_metadata_store import LineageMetadataStore
from app.services.lineage_service import LineageService
from app.services.source_correction_store import SourceCorrectionStore
from app.workers import lineage_worker


class _Model(BaseModel):
    key: str


@pytest.mark.parametrize(
    "store_type",
    [
        ExecutionRegistry,
        ComputeJobStore,
        AsyncResultStore,
        LineageMetadataStore,
        CompositeMetadataStore,
        SourceCorrectionStore,
    ],
)
def test_each_store_read_only_verification_refuses_empty_database(store_type, tmp_path):
    store = store_type(f"sqlite:///{tmp_path / 'unapplied.db'}")
    try:
        with pytest.raises(DurableSchemaMigrationRequiredError):
            store.verify_schema()
        assert inspect(store._engine).get_table_names() == []
    finally:
        store._engine.dispose()


@pytest.mark.parametrize(
    "store_type",
    [
        ExecutionRegistry,
        ComputeJobStore,
        AsyncResultStore,
        LineageMetadataStore,
        CompositeMetadataStore,
        SourceCorrectionStore,
    ],
)
def test_each_store_owner_applied_schema_verifies_without_mutation(store_type, tmp_path):
    store = store_type(f"sqlite:///{tmp_path / 'applied.db'}")
    try:
        store.create_schema()
        statements = []
        event.listen(store._engine, "before_cursor_execute", lambda _, __, sql, *args: statements.append(sql))
        store.verify_schema()
        assert statements
        assert all(
            not sql.lstrip().upper().startswith(("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE"))
            for sql in statements
        )
    finally:
        store._engine.dispose()


def test_bootstrap_durable_metadata_stores_calls_all_store_bootstraps(mocker):
    execution_store = mocker.Mock()
    compute_store = mocker.Mock()
    async_result_store_ = mocker.Mock()
    lineage_store = mocker.Mock()
    composite_store = mocker.Mock()
    correction_store = mocker.Mock()

    bootstrap_durable_metadata_stores(
        execution_store=execution_store,
        compute_store=compute_store,
        async_result_store_=async_result_store_,
        lineage_store=lineage_store,
        composite_store=composite_store,
        correction_store=correction_store,
    )

    execution_store.create_schema.assert_called_once_with()
    compute_store.create_schema.assert_called_once_with()
    async_result_store_.create_schema.assert_called_once_with()
    lineage_store.create_schema.assert_called_once_with()
    composite_store.create_schema.assert_called_once_with()
    correction_store.create_schema.assert_called_once_with()


def test_bootstrap_durable_metadata_stores_supports_recovery_drill_on_legacy_lineage_schema(monkeypatch, tmp_path):
    database_path = tmp_path / "recovery.db"
    execution_store = ExecutionRegistry(f"sqlite:///{database_path}")
    compute_store = ComputeJobStore(f"sqlite:///{database_path}")
    async_result_store_ = AsyncResultStore(f"sqlite:///{database_path}")
    lineage_store = LineageMetadataStore(f"sqlite:///{database_path}")
    composite_store = CompositeMetadataStore(f"sqlite:///{database_path}")
    correction_store = SourceCorrectionStore(f"sqlite:///{database_path}")

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
        composite_store=composite_store,
        correction_store=correction_store,
    )

    with lineage_store._engine.connect() as connection:
        require_metadata_schema(connection, LineageBase.metadata)

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
