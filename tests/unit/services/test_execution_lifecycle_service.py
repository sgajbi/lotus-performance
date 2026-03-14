from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.services.execution_lifecycle_service import complete_execution_with_lineage
from app.services.execution_registry import ExecutionStageStatus, ExecutionStatus, execution_registry


class _MockModel(BaseModel):
    key: str


@pytest.fixture(autouse=True)
def _clean_execution_registry():
    execution_registry.create_schema()
    execution_registry.clear_all_records()
    yield
    execution_registry.clear_all_records()


def test_complete_execution_with_lineage_marks_execution_complete(mocker):
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
    assert record.status == ExecutionStatus.COMPLETE
    stages = {stage.stage_name: stage for stage in record.stages}
    assert stages["execution"].status == ExecutionStageStatus.COMPLETE
    assert stages["execution"].details == {"rows": 2}
    assert stages["lineage_materialization"].status == ExecutionStageStatus.IN_PROGRESS


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
    assert record.error_message == "Failed to enqueue lineage capture: lineage queue unavailable"
    stages = {stage.stage_name: stage for stage in record.stages}
    assert stages["execution"].status == ExecutionStageStatus.COMPLETE
    assert stages["lineage_materialization"].status == ExecutionStageStatus.FAILED
    assert stages["lineage_materialization"].error_message == "Failed to enqueue lineage capture: lineage queue unavailable"
