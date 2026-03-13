from uuid import uuid4

import pytest

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
