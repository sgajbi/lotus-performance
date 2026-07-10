from __future__ import annotations

from typing import Any
from uuid import UUID

from app.services.execution_registry import execution_registry
from app.services.execution_stage_errors import safe_unexpected_failure_message
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION, EXECUTION_STAGE_LINEAGE_MATERIALIZATION
from app.services.lineage_service import lineage_service


def record_execution_failure(
    *,
    calculation_id: UUID,
    message: str,
    execution_stage_started: bool = False,
    lineage_stage_started: bool = False,
) -> None:
    if lineage_stage_started:
        execution_registry.fail_stage_and_execution(calculation_id, EXECUTION_STAGE_LINEAGE_MATERIALIZATION, message)
    elif execution_stage_started:
        execution_registry.fail_stage_and_execution(calculation_id, EXECUTION_STAGE_EXECUTION, message)
    else:
        execution_registry.mark_failed(calculation_id, message)


def complete_execution_with_lineage(
    *,
    calculation_id: UUID,
    calculation_type: str,
    request_model: Any,
    response_model: Any,
    execution_details: dict[str, Any] | None = None,
    calculation_details: dict[str, Any] | None = None,
) -> None:
    execution_registry.mark_running(calculation_id)
    execution_registry.complete_stage(
        calculation_id,
        EXECUTION_STAGE_EXECUTION,
        details=execution_details or {},
    )
    execution_registry.start_stage(calculation_id, EXECUTION_STAGE_LINEAGE_MATERIALIZATION)
    try:
        lineage_service.enqueue_capture(
            calculation_id=calculation_id,
            calculation_type=calculation_type,
            request_model=request_model,
            response_model=response_model,
            calculation_details=calculation_details or {},
        )
    except Exception:
        record_execution_failure(
            calculation_id=calculation_id,
            message=safe_unexpected_failure_message("Lineage capture enqueue"),
            lineage_stage_started=True,
        )
        raise
