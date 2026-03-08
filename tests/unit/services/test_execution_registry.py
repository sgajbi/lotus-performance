from uuid import uuid4

import pytest

from app.services.execution_registry import (
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
