from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect

from app.services.execution_registry import (
    AnalyticsExecutionModel,
    AnalyticsExecutionStageModel,
    AnalyticsUpstreamSnapshotModel,
    ExecutionRegistrationStatus,
    ExecutionRegistry,
    ExecutionStageStatus,
    ExecutionStatus,
    _execution_model_for_registration,
    _execution_record_from_model,
    _record_missing_upstream_snapshot,
    _upstream_snapshot_model_from_payload,
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


def test_execution_registry_bounds_malformed_execution_json_fields(tmp_path, caplog):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()

    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="TWR",
        portfolio_id="PORT-MALFORMED",
        requested_window={"report_end_date": "2026-03-31"},
    )
    registry.start_stage(calculation_id, "execution")
    registry.complete_stage(calculation_id, "execution", details={"rows": 2})
    with registry._session() as session:
        execution = registry._get_execution_model(session, calculation_id)
        stage = registry._get_stage_model(session, calculation_id, "execution")
        execution.requested_window_json = "{not-json"
        stage.details_json = "[1, 2, 3]"

    with caplog.at_level("WARNING", logger="app.services.execution_registry"):
        record = registry.get_execution(calculation_id)

    assert record is not None
    assert record.requested_window == {}
    assert record.stages[0].details is None
    assert f"calculation_id={calculation_id}" in caplog.text


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


def test_execution_registry_preserves_empty_upstream_snapshot_paging_metadata(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()
    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-EMPTY-PAGING",
    )

    registry.record_upstream_snapshot(
        calculation_id=calculation_id,
        snapshot_id="snap-empty-paging",
        upstream_endpoint="portfolio_timeseries",
        source_identifier="PORT-EMPTY-PAGING",
        as_of_date="2026-02-27",
        request_fingerprint="req-empty",
        response_fingerprint="resp-empty",
        retrieval_status="200",
        paging_metadata={},
    )

    snapshots = registry.list_upstream_snapshots(calculation_id)

    assert len(snapshots) == 1
    assert snapshots[0].paging_metadata == {}


def test_execution_registry_bounds_malformed_upstream_snapshot_paging_metadata(tmp_path, caplog):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()
    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-MALFORMED-PAGING",
    )
    registry.record_upstream_snapshot(
        calculation_id=calculation_id,
        snapshot_id="snap-invalid-paging",
        upstream_endpoint="portfolio_timeseries",
        source_identifier="PORT-MALFORMED-PAGING",
        as_of_date="2026-02-27",
        request_fingerprint="req-invalid",
        response_fingerprint="resp-invalid",
        retrieval_status="200",
        paging_metadata={"page_token": "n1"},
    )
    with registry._session() as session:
        snapshot = session.get(AnalyticsUpstreamSnapshotModel, "snap-invalid-paging")
        assert snapshot is not None
        snapshot.paging_metadata_json = "{not-json"

    with caplog.at_level("WARNING", logger="app.services.execution_registry"):
        snapshots = registry.list_upstream_snapshots(calculation_id)

    assert len(snapshots) == 1
    assert snapshots[0].paging_metadata is None
    assert f"calculation_id={calculation_id}" in caplog.text


def test_execution_registry_ignores_duplicate_upstream_snapshots(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()
    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-DUP",
    )

    snapshots = [
        {
            "snapshot_id": "snap-dup",
            "upstream_endpoint": "position_timeseries",
            "source_identifier": "PORT-DUP",
            "as_of_date": "2026-03-30",
            "request_fingerprint": "req-dup",
            "response_fingerprint": "resp-dup",
            "retrieval_status": "200",
            "paging_metadata": {"page_token": None},
        }
    ]

    registry.record_upstream_snapshots(calculation_id=calculation_id, snapshots=snapshots)
    registry.record_upstream_snapshots(calculation_id=calculation_id, snapshots=snapshots)
    registry.record_upstream_snapshot(
        calculation_id=calculation_id,
        snapshot_id="snap-dup",
        upstream_endpoint="position_timeseries",
        source_identifier="PORT-DUP",
        as_of_date="2026-03-30",
        request_fingerprint="req-dup",
        response_fingerprint="resp-dup",
        retrieval_status="200",
        paging_metadata={"page_token": None},
    )

    record = registry.get_execution(calculation_id)

    assert record is not None
    assert len(record.upstream_snapshots) == 1
    assert record.upstream_snapshots[0].snapshot_id == "snap-dup"


def test_upstream_snapshot_model_projection_preserves_payload_fields():
    calculation_id = uuid4()
    created_at = datetime(2026, 6, 13, tzinfo=timezone.utc)

    model = _upstream_snapshot_model_from_payload(
        calculation_id=calculation_id,
        snapshot={
            "snapshot_id": "snap-model",
            "upstream_endpoint": "portfolio_timeseries",
            "source_identifier": "PORT-MODEL",
            "as_of_date": "2026-06-13",
            "request_fingerprint": "req-model",
            "response_fingerprint": "resp-model",
            "retrieval_status": "200",
            "paging_metadata": {"page_token": "next"},
        },
        created_at=created_at,
    )

    assert model.snapshot_id == "snap-model"
    assert model.calculation_id == str(calculation_id)
    assert model.upstream_endpoint == "portfolio_timeseries"
    assert model.source_identifier == "PORT-MODEL"
    assert model.as_of_date == "2026-06-13"
    assert model.request_fingerprint == "req-model"
    assert model.response_fingerprint == "resp-model"
    assert model.retrieval_status == "200"
    assert model.paging_metadata_json == '{"page_token": "next"}'
    assert model.created_at_utc == created_at


def test_record_missing_upstream_snapshot_tracks_inserted_snapshot_ids(tmp_path):
    registry = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    registry.create_schema()
    calculation_id = uuid4()
    registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-MISSING-SNAPSHOT",
    )
    snapshot = {
        "snapshot_id": "snap-policy",
        "upstream_endpoint": "portfolio_timeseries",
        "source_identifier": "PORT-MISSING-SNAPSHOT",
        "as_of_date": "2026-06-16",
        "request_fingerprint": "req-policy",
        "response_fingerprint": "resp-policy",
        "retrieval_status": "200",
    }
    existing_snapshot_ids: set[str] = set()

    with registry._session() as session:
        inserted = _record_missing_upstream_snapshot(
            session,
            calculation_id=calculation_id,
            snapshot=snapshot,
            created_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
            existing_snapshot_ids=existing_snapshot_ids,
        )
        skipped = _record_missing_upstream_snapshot(
            session,
            calculation_id=calculation_id,
            snapshot=snapshot,
            created_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
            existing_snapshot_ids=existing_snapshot_ids,
        )

    assert inserted
    assert not skipped
    assert existing_snapshot_ids == {"snap-policy"}
    assert [snapshot.snapshot_id for snapshot in registry.list_upstream_snapshots(calculation_id)] == ["snap-policy"]


def test_execution_replay_policy_matches_complete_execution_identity():
    existing = AnalyticsExecutionModel(
        calculation_id=str(uuid4()),
        analytics_type="TWR",
        portfolio_id="PORT-REPLAY",
        execution_mode="async",
        status="pending",
        requested_window_json='{"report_end_date": "2026-06-16"}',
        input_fingerprint="input-1",
        calculation_hash="calc-1",
        created_at_utc=datetime(2026, 6, 16, tzinfo=timezone.utc),
    )

    assert ExecutionRegistry._is_replay_of_existing_execution(
        existing=existing,
        analytics_type="TWR",
        portfolio_id="PORT-REPLAY",
        execution_mode="async",
        requested_window_json='{"report_end_date": "2026-06-16"}',
        input_fingerprint="input-1",
        calculation_hash="calc-1",
    )
    assert not ExecutionRegistry._is_replay_of_existing_execution(
        existing=existing,
        analytics_type="TWR",
        portfolio_id="PORT-REPLAY",
        execution_mode="async",
        requested_window_json='{"report_end_date": "2026-06-17"}',
        input_fingerprint="input-1",
        calculation_hash="calc-1",
    )


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


def test_execution_registration_model_factory_projects_pending_execution_contract():
    calculation_id = uuid4()
    created_at = datetime(2026, 6, 19, 8, 30, tzinfo=timezone.utc)

    execution = _execution_model_for_registration(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT-FACTORY",
        execution_mode="async",
        requested_window_json='{"from_date": "2026-01-01", "to_date": "2026-06-19"}',
        input_fingerprint="sha256:input",
        calculation_hash="sha256:calc",
        created_at=created_at,
    )

    assert execution.calculation_id == str(calculation_id)
    assert execution.status == ExecutionStatus.PENDING.value
    assert execution.requested_window_json == '{"from_date": "2026-01-01", "to_date": "2026-06-19"}'
    assert execution.input_fingerprint == "sha256:input"
    assert execution.calculation_hash == "sha256:calc"
    assert execution.created_at_utc == created_at
    assert execution.started_at_utc is None
    assert execution.completed_at_utc is None
    assert execution.error_message is None


def test_execution_record_projection_orders_stages_and_formats_execution_contract():
    calculation_id = uuid4()
    execution = AnalyticsExecutionModel(
        calculation_id=str(calculation_id),
        analytics_type="Attribution",
        portfolio_id="PORT-PROJECTION",
        execution_mode="sync",
        status=ExecutionStatus.COMPLETE.value,
        requested_window_json='{"from_date": "2026-01-01", "to_date": "2026-06-19"}',
        input_fingerprint="sha256:projection-input",
        calculation_hash="sha256:projection-calc",
        error_message=None,
        created_at_utc=datetime(2026, 6, 19, 8, 0, tzinfo=timezone.utc),
        started_at_utc=datetime(2026, 6, 19, 8, 1, tzinfo=timezone.utc),
        completed_at_utc=datetime(2026, 6, 19, 8, 2, tzinfo=timezone.utc),
    )
    execution.stages = [
        AnalyticsExecutionStageModel(
            calculation_id=str(calculation_id),
            stage_name="lineage_materialization",
            status=ExecutionStageStatus.COMPLETE.value,
            started_at_utc=None,
            completed_at_utc=datetime(2026, 6, 19, 8, 3, tzinfo=timezone.utc),
            details_json='{"artifact_names": ["lineage.json"]}',
            error_message=None,
        ),
        AnalyticsExecutionStageModel(
            calculation_id=str(calculation_id),
            stage_name="execution",
            status=ExecutionStageStatus.COMPLETE.value,
            started_at_utc=datetime(2026, 6, 19, 8, 1, tzinfo=timezone.utc),
            completed_at_utc=datetime(2026, 6, 19, 8, 2, tzinfo=timezone.utc),
            details_json='{"rows": 3}',
            error_message=None,
        ),
    ]

    record = _execution_record_from_model(execution=execution, upstream_snapshots=[])

    assert record.calculation_id == calculation_id
    assert record.analytics_type == "Attribution"
    assert record.portfolio_id == "PORT-PROJECTION"
    assert record.execution_mode == "sync"
    assert record.status == ExecutionStatus.COMPLETE
    assert record.requested_window == {"from_date": "2026-01-01", "to_date": "2026-06-19"}
    assert record.input_fingerprint == "sha256:projection-input"
    assert record.calculation_hash == "sha256:projection-calc"
    assert record.created_at_utc == "2026-06-19T08:00:00Z"
    assert record.started_at_utc == "2026-06-19T08:01:00Z"
    assert record.completed_at_utc == "2026-06-19T08:02:00Z"
    assert [stage.stage_name for stage in record.stages] == ["execution", "lineage_materialization"]
    assert record.stages[0].details == {"rows": 3}
    assert record.stages[1].details == {"artifact_names": ["lineage.json"]}
    assert record.upstream_snapshots == []


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
