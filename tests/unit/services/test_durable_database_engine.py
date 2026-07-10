from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services.durable_database_engine import (
    DurableDatabaseEnginePolicy,
    durable_database_engine_kwargs,
)
from app.services.execution_registry import AnalyticsExecutionModel, ExecutionRegistry, ExecutionStatus


def _policy() -> DurableDatabaseEnginePolicy:
    return DurableDatabaseEnginePolicy(
        connect_timeout_seconds=7,
        pool_pre_ping=True,
        pool_size=9,
        max_overflow=4,
        pool_recycle_seconds=1200,
        statement_timeout_ms=25000,
        lock_timeout_ms=3000,
        sqlite_busy_timeout_ms=4500,
    )


def test_sqlite_engine_policy_sets_busy_timeout_and_thread_contract() -> None:
    kwargs = durable_database_engine_kwargs("sqlite:///local.db", policy=_policy())

    assert kwargs == {
        "connect_args": {
            "check_same_thread": False,
            "timeout": 4.5,
        }
    }


def test_postgres_engine_policy_sets_pool_health_and_timeout_contract() -> None:
    kwargs = durable_database_engine_kwargs(
        "postgresql+psycopg://lotus:secret@db:5432/lotus_performance",
        policy=_policy(),
    )

    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_size"] == 9
    assert kwargs["max_overflow"] == 4
    assert kwargs["pool_recycle"] == 1200
    assert kwargs["connect_args"]["connect_timeout"] == 7
    assert "statement_timeout=25000" in kwargs["connect_args"]["options"]
    assert "lock_timeout=3000" in kwargs["connect_args"]["options"]


def test_postgres_engine_policy_preserves_url_connection_options() -> None:
    kwargs = durable_database_engine_kwargs(
        "postgresql+psycopg://lotus:secret@db:5432/lotus_performance?options=-csearch_path%3Dbench_schema",
        policy=_policy(),
    )

    options = kwargs["connect_args"]["options"]

    assert "-csearch_path=bench_schema" in options
    assert "statement_timeout=25000" in options
    assert "lock_timeout=3000" in options


def test_execution_registry_still_commits_through_shared_engine_policy(tmp_path) -> None:
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()

    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-1",
        execution_mode="async",
        requested_window={"from": "2026-01-01", "to": "2026-01-31"},
    )

    assert registry.get_execution(calculation_id) is not None


def test_execution_registry_rolls_back_shared_engine_session_failures(tmp_path) -> None:
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()

    with pytest.raises(RuntimeError, match="force rollback"):
        with registry._session() as session:
            session.add(
                AnalyticsExecutionModel(
                    calculation_id=str(calculation_id),
                    analytics_type="ReturnsSeries",
                    portfolio_id="PORT-1",
                    execution_mode="async",
                    status=ExecutionStatus.PENDING.value,
                    requested_window_json="{}",
                    created_at_utc=datetime.now(timezone.utc),
                )
            )
            raise RuntimeError("force rollback")

    assert registry.get_execution(calculation_id) is None
