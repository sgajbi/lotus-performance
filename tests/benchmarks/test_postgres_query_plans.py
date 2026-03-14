import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.services.compute_job_store import ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from app.services.lineage_metadata_store import LineageMetadataStore

POSTGRES_PLAN_DATABASE_URL = os.getenv(
    "LOTUS_POSTGRES_PLAN_DATABASE_URL",
    "postgresql+psycopg://lotus:lotus@127.0.0.1:5435/lotus_performance",
)
COMPUTE_QUEUE_PLAN_ROWS = 5_000
LINEAGE_QUEUE_PLAN_ROWS = 1_000
EXECUTION_POLLING_PLAN_EXECUTIONS = 25
EXECUTION_POLLING_PLAN_SNAPSHOTS_PER_EXECUTION = 100


@pytest.fixture(scope="module")
def postgres_database_url():
    engine = create_engine(POSTGRES_PLAN_DATABASE_URL, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(f"PostgreSQL plan database unavailable at {POSTGRES_PLAN_DATABASE_URL}")
    finally:
        engine.dispose()
    return POSTGRES_PLAN_DATABASE_URL


def _explain_json(database_url: str, statement) -> dict[str, object]:
    engine = create_engine(database_url, future=True)
    try:
        compiled = statement.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True})
        with engine.connect() as connection:
            explain_row = connection.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {compiled}").scalar_one()
    finally:
        engine.dispose()
    return explain_row[0]["Plan"]


def _analyze_tables(database_url: str, *table_names: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            for table_name in table_names:
                connection.exec_driver_sql(f"ANALYZE {table_name}")
    finally:
        engine.dispose()


def _collect_node_types(plan: dict[str, object]) -> list[str]:
    node_types = [str(plan.get("Node Type", ""))]
    for child in plan.get("Plans", []):
        node_types.extend(_collect_node_types(child))
    return node_types


def _collect_relation_names(plan: dict[str, object]) -> list[str]:
    relation_names = []
    relation_name = plan.get("Relation Name")
    if relation_name is not None:
        relation_names.append(str(relation_name))
    for child in plan.get("Plans", []):
        relation_names.extend(_collect_relation_names(child))
    return relation_names


def _collect_index_names(plan: dict[str, object]) -> list[str]:
    index_names = []
    index_name = plan.get("Index Name")
    if index_name is not None:
        index_names.append(str(index_name))
    for child in plan.get("Plans", []):
        index_names.extend(_collect_index_names(child))
    return index_names


def test_postgres_compute_queue_stats_plan_contract(postgres_database_url):
    store = ComputeJobStore(postgres_database_url)
    store.create_schema()
    store.clear_all_records()

    for row_index in range(COMPUTE_QUEUE_PLAN_ROWS):
        store.enqueue_job(
            calculation_id=uuid4(),
            analytics_type="ReturnsSeries",
            request_payload={"row_index": row_index},
        )

    _analyze_tables(postgres_database_url, "analytics_compute_job")
    plan = _explain_json(postgres_database_url, store._build_queue_stats_statement())
    node_types = _collect_node_types(plan)
    relation_names = _collect_relation_names(plan)

    assert "Aggregate" in node_types
    assert "Sort" not in node_types
    assert "analytics_compute_job" in relation_names


def test_postgres_lineage_queue_stats_plan_contract(postgres_database_url):
    store = LineageMetadataStore(postgres_database_url)
    store.create_schema()
    store.clear_all_records()

    for row_index in range(LINEAGE_QUEUE_PLAN_ROWS):
        store.enqueue_lineage_payload(
            calculation_id=uuid4(),
            calculation_type="TWR",
            request_json="{}",
            response_json="{}",
            details={"row_index": str(row_index)},
        )

    _analyze_tables(postgres_database_url, "lineage_records", "lineage_payloads")
    plan = _explain_json(
        postgres_database_url,
        store._build_pending_payload_stats_statement(now=datetime.now(timezone.utc)),
    )
    node_types = _collect_node_types(plan)
    relation_names = _collect_relation_names(plan)

    assert "Aggregate" in node_types
    assert "Sort" not in node_types
    assert "lineage_payloads" in relation_names
    assert "lineage_records" in relation_names


def test_postgres_execution_polling_plan_contract(postgres_database_url):
    registry = ExecutionRegistry(postgres_database_url)
    registry.create_schema()
    registry.clear_all_records()

    target_calculation_id = uuid4()
    execution_ids = [target_calculation_id, *[uuid4() for _ in range(EXECUTION_POLLING_PLAN_EXECUTIONS - 1)]]
    for execution_index, calculation_id in enumerate(execution_ids):
        registry.create_execution(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            portfolio_id=f"PF-{execution_index}",
            execution_mode="async",
            requested_window={"mode": "EXPLICIT"},
        )
        registry.record_upstream_snapshots(
            calculation_id=calculation_id,
            snapshots=[
                {
                    "snapshot_id": f"{calculation_id}-{snapshot_index}",
                    "upstream_endpoint": "portfolio_timeseries",
                    "source_identifier": f"PF-{execution_index}",
                    "as_of_date": "2026-03-14",
                    "request_fingerprint": f"request-{execution_index}-{snapshot_index}",
                    "response_fingerprint": f"response-{execution_index}-{snapshot_index}",
                    "retrieval_status": "complete",
                    "paging_metadata": {"page": snapshot_index},
                }
                for snapshot_index in range(EXECUTION_POLLING_PLAN_SNAPSHOTS_PER_EXECUTION)
            ],
        )

    _analyze_tables(postgres_database_url, "analytics_upstream_snapshot")
    snapshot_plan = _explain_json(
        postgres_database_url,
        registry._build_upstream_snapshots_statement(target_calculation_id),
    )
    snapshot_index_names = _collect_index_names(snapshot_plan)
    node_types = _collect_node_types(snapshot_plan)

    assert "ix_upstream_snapshot_calculation_created_at" in snapshot_index_names
    assert "Seq Scan" not in node_types
