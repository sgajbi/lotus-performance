from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect

from app.services.execution_registry import (
    ExecutionRegistrationStatus,
    ExecutionRegistry,
    ExecutionStageStatus,
    ExecutionStatus,
)


def test_execution_registry_records_lifecycle_and_stages(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()

    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="TWR",
        portfolio_id="PORT-1",
        requested_window={"report_end_date": "2025-01-01"},
        input_fingerprint="sha256:input",
        calculation_hash="sha256:calc",
    )
    registry.mark_running(calculation_id)
    registry.start_stage(calculation_id, "execution")
    registry.complete_stage(calculation_id, "execution", details={"rows": 2})
    registry.start_stage(calculation_id, "lineage_materialization")
    registry.complete_stage(calculation_id, "lineage_materialization", details={"artifact_names": ["a.json"]})
    registry.mark_complete(calculation_id)

    record = registry.get_execution(calculation_id)

    assert record is not None
    assert record.status == ExecutionStatus.COMPLETE
    assert record.analytics_type == "TWR"
    assert record.requested_window["report_end_date"] == "2025-01-01"
    assert [stage.stage_name for stage in record.stages] == ["execution", "lineage_materialization"]
    assert record.stages[0].status == ExecutionStageStatus.COMPLETE
    assert record.stages[0].details == {"rows": 2}
    assert record.stages[1].details == {"artifact_names": ["a.json"]}


def test_execution_registry_marks_failures(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()

    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="MWR",
        portfolio_id="PORT-2",
    )
    registry.mark_running(calculation_id)
    registry.start_stage(calculation_id, "execution")
    registry.fail_stage(calculation_id, "execution", "boom")
    registry.mark_failed(calculation_id, "boom")

    record = registry.get_execution(calculation_id)

    assert record is not None
    assert record.status == ExecutionStatus.FAILED
    assert record.error_message == "boom"
    assert record.stages[0].status == ExecutionStageStatus.FAILED
    assert record.stages[0].error_message == "boom"


def test_execution_registry_raises_for_missing_stage(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()
    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        portfolio_id="PORT-3",
    )

    with pytest.raises(KeyError):
        registry.complete_stage(calculation_id, "execution")


def test_execution_registry_records_upstream_snapshots(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()
    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-4",
    )

    registry.record_upstream_snapshot(
        calculation_id=calculation_id,
        snapshot_id="snap-1",
        upstream_endpoint="portfolio_timeseries",
        source_identifier="PORT-4",
        as_of_date="2026-02-27",
        request_fingerprint="req-1",
        response_fingerprint="resp-1",
        retrieval_status="200",
        paging_metadata={"page_token": "n1"},
    )

    record = registry.get_execution(calculation_id)

    assert record is not None
    assert len(record.upstream_snapshots) == 1
    snapshot = record.upstream_snapshots[0]
    assert snapshot.snapshot_id == "snap-1"
    assert snapshot.upstream_endpoint == "portfolio_timeseries"
    assert snapshot.paging_metadata == {"page_token": "n1"}


def test_execution_registry_clear_all_records_removes_upstream_snapshots(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()
    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-5",
    )
    registry.record_upstream_snapshot(
        calculation_id=calculation_id,
        snapshot_id="snap-clear",
        upstream_endpoint="portfolio_timeseries",
        source_identifier="PORT-5",
        as_of_date="2026-02-27",
        request_fingerprint="req-clear",
        response_fingerprint="resp-clear",
        retrieval_status="200",
    )

    registry.clear_all_records()

    assert registry.get_execution(calculation_id) is None


def test_execution_registry_register_execution_distinguishes_create_replay_and_conflict(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()

    created = registry.register_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-6",
        execution_mode="async",
        requested_window={"to_date": "2026-02-27"},
        input_fingerprint="sha256:input-a",
        calculation_hash="sha256:calc-a",
    )
    replay = registry.register_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-6",
        execution_mode="async",
        requested_window={"to_date": "2026-02-27"},
        input_fingerprint="sha256:input-a",
        calculation_hash="sha256:calc-a",
    )
    conflict = registry.register_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-6",
        execution_mode="async",
        requested_window={"to_date": "2026-02-28"},
        input_fingerprint="sha256:input-b",
        calculation_hash="sha256:calc-b",
    )

    assert created.status == ExecutionRegistrationStatus.CREATED
    assert replay.status == ExecutionRegistrationStatus.REPLAY
    assert replay.existing_status == ExecutionStatus.PENDING
    assert conflict.status == ExecutionRegistrationStatus.CONFLICT
    assert conflict.existing_execution_mode == "async"


def test_execution_registry_declares_upstream_snapshot_ordering_index(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()

    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspect(registry._engine).get_indexes("analytics_upstream_snapshot")
    }

    assert indexes["ix_upstream_snapshot_calculation_created_at"] == ("calculation_id", "created_at_utc")
    assert "ix_analytics_upstream_snapshot_calculation_id" not in indexes


def test_execution_registry_formats_sqlite_timestamps_as_utc(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()
    created_at = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    started_at = datetime(2026, 3, 14, 12, 5, tzinfo=timezone.utc)
    completed_at = datetime(2026, 3, 14, 12, 10, tzinfo=timezone.utc)

    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="TWR",
        portfolio_id="PORT-UTC",
    )

    with registry._session() as session:
        execution = registry._get_execution_model(session, calculation_id)
        execution.created_at_utc = created_at
        execution.started_at_utc = started_at
        execution.completed_at_utc = completed_at

    record = registry.get_execution(calculation_id)

    assert record is not None
    assert record.created_at_utc == "2026-03-14T12:00:00Z"
    assert record.started_at_utc == "2026-03-14T12:05:00Z"
    assert record.completed_at_utc == "2026-03-14T12:10:00Z"


def test_execution_registry_lists_and_deletes_terminal_executions_older_than_cutoff(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    old_id = uuid4()
    recent_id = uuid4()

    for calculation_id in (old_id, recent_id):
        registry.create_execution(
            calculation_id=calculation_id,
            analytics_type="TWR",
            portfolio_id="PORT-RETENTION",
        )
        registry.mark_complete(calculation_id)

    with registry._session() as session:
        old_row = registry._get_execution_model(session, old_id)
        recent_row = registry._get_execution_model(session, recent_id)
        old_row.completed_at_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
        recent_row.completed_at_utc = datetime(2026, 3, 10, tzinfo=timezone.utc)

    cutoff = datetime(2026, 2, 1, tzinfo=timezone.utc)

    assert registry.list_terminal_execution_ids_older_than(cutoff) == [str(old_id)]
    assert registry.delete_executions([str(old_id)]) == 1
    assert registry.get_execution(old_id) is None
    assert registry.get_execution(recent_id) is not None


def test_execution_registry_delete_executions_returns_zero_for_empty_input(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()

    assert registry.delete_executions([]) == 0


def test_execution_registry_fails_in_progress_stages(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()
    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="Attribution",
        portfolio_id="PORT-STAGE",
    )
    registry.start_stage(calculation_id, "execution")
    registry.start_stage(calculation_id, "lineage_materialization")
    registry.complete_stage(calculation_id, "execution")

    registry.fail_in_progress_stages(calculation_id, "worker crashed")

    record = registry.get_execution(calculation_id)

    assert record is not None
    stages = {stage.stage_name: stage for stage in record.stages}
    assert stages["execution"].status == ExecutionStageStatus.COMPLETE
    assert stages["lineage_materialization"].status == ExecutionStageStatus.FAILED
    assert stages["lineage_materialization"].error_message == "worker crashed"
