from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.services.execution_lifecycle_service import complete_execution_with_lineage, record_execution_cancellation
from app.services.execution_registry import ExecutionStageStatus, ExecutionStatus, execution_registry


class _MockModel(BaseModel):
    key: str


@pytest.fixture(autouse=True)
def _clean_execution_registry():
    execution_registry.create_schema()
    execution_registry.clear_all_records()
    yield
    execution_registry.clear_all_records()


def test_complete_execution_with_lineage_keeps_execution_running_until_lineage_materializes(mocker):
    calculation_id = uuid4()
    execution_registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="TEST",
        portfolio_id="PORT-1",
    )
    execution_registry.mark_running(calculation_id)
    execution_registry.start_stage(calculation_id, "execution")

    enqueue_capture = mocker.patch("app.services.execution_lifecycle_service.lineage_service.enqueue_capture")

    complete_execution_with_lineage(
        calculation_id=calculation_id,
        calculation_type="TEST",
        request_model=_MockModel(key="request"),
        response_model=_MockModel(key="response"),
        execution_details={"rows": 2},
    )

    enqueue_capture.assert_called_once()
    record = execution_registry.get_execution(calculation_id)
    assert record is not None
    assert record.status == ExecutionStatus.RUNNING
    assert record.completed_at_utc is None
    stages = {stage.stage_name: stage for stage in record.stages}
    assert stages["execution"].status == ExecutionStageStatus.COMPLETE
    assert stages["execution"].details == {"rows": 2}
    assert stages["lineage_materialization"].status == ExecutionStageStatus.IN_PROGRESS
    assert stages["lineage_materialization"].completed_at_utc is None


def test_complete_execution_with_lineage_fails_lineage_stage_when_enqueue_raises(mocker):
    calculation_id = uuid4()
    execution_registry.create_execution(
        calculation_id=calculation_id,
        analytics_type="TEST",
        portfolio_id="PORT-1",
    )
    execution_registry.mark_running(calculation_id)
    execution_registry.start_stage(calculation_id, "execution")

    mocker.patch(
        "app.services.execution_lifecycle_service.lineage_service.enqueue_capture",
        side_effect=RuntimeError("lineage queue unavailable"),
    )

    with pytest.raises(RuntimeError, match="lineage queue unavailable"):
        complete_execution_with_lineage(
            calculation_id=calculation_id,
            calculation_type="TEST",
            request_model=_MockModel(key="request"),
            response_model=_MockModel(key="response"),
        )

    record = execution_registry.get_execution(calculation_id)
    assert record is not None
    assert record.status == ExecutionStatus.FAILED
    assert record.error_message == "Lineage capture enqueue failed unexpectedly. Use the correlation_id for support."
    stages = {stage.stage_name: stage for stage in record.stages}
    assert stages["execution"].status == ExecutionStageStatus.COMPLETE
    assert stages["lineage_materialization"].status == ExecutionStageStatus.FAILED
    assert (
        stages["lineage_materialization"].error_message
        == "Lineage capture enqueue failed unexpectedly. Use the correlation_id for support."
    )


def test_record_execution_cancellation_fences_execution_before_lineage(mocker):
    calculation_id = uuid4()
    calls: list[str] = []
    mark_failed = mocker.patch(
        "app.services.execution_lifecycle_service.execution_registry.mark_failed",
        side_effect=lambda *_args: calls.append("execution_failed"),
    )
    fail_stages = mocker.patch(
        "app.services.execution_lifecycle_service.execution_registry.fail_in_progress_stages",
        side_effect=lambda *_args: calls.append("stages_failed"),
    )
    fence_lineage = mocker.patch(
        "app.services.execution_lifecycle_service.lineage_metadata_store.mark_failed_if_present",
        side_effect=lambda *_args: calls.append("lineage_failed"),
    )

    record_execution_cancellation(
        calculation_id=calculation_id,
        message="Workspace summary calculation cancelled.",
    )

    assert calls == ["execution_failed", "stages_failed", "lineage_failed"]
    mark_failed.assert_called_once_with(calculation_id, "Workspace summary calculation cancelled.")
    fail_stages.assert_called_once_with(calculation_id, "Workspace summary calculation cancelled.")
    fence_lineage.assert_called_once_with(calculation_id, "Workspace summary calculation cancelled.")
