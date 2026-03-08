from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.execution_registry import execution_registry

router = APIRouter(tags=["Performance"])


class ExecutionStageResponse(BaseModel):
    stage_name: str = Field(description="Internal execution stage name.")
    status: str = Field(description="Current stage status.")
    started_at_utc: str | None = Field(default=None, description="UTC timestamp when the stage started.")
    completed_at_utc: str | None = Field(default=None, description="UTC timestamp when the stage completed.")
    details: dict[str, Any] | None = Field(default=None, description="Optional stage metadata details.")
    error_message: str | None = Field(default=None, description="Failure detail if the stage failed.")


class ExecutionResponse(BaseModel):
    calculation_id: UUID
    analytics_type: str
    portfolio_id: str | None
    execution_mode: str
    status: str
    requested_window: dict[str, Any]
    input_fingerprint: str | None
    calculation_hash: str | None
    error_message: str | None
    created_at_utc: str
    started_at_utc: str | None
    completed_at_utc: str | None
    stages: list[ExecutionStageResponse]


@router.get(
    "/executions/{calculation_id}",
    response_model=ExecutionResponse,
    summary="Retrieve execution lifecycle state",
    description="Returns durable execution and stage metadata for a lotus-performance calculation.",
)
async def get_execution(calculation_id: UUID) -> ExecutionResponse:
    record = execution_registry.get_execution(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution data not found for the given calculation_id.",
        )

    return ExecutionResponse(
        calculation_id=record.calculation_id,
        analytics_type=record.analytics_type,
        portfolio_id=record.portfolio_id,
        execution_mode=record.execution_mode,
        status=record.status.value,
        requested_window=record.requested_window,
        input_fingerprint=record.input_fingerprint,
        calculation_hash=record.calculation_hash,
        error_message=record.error_message,
        created_at_utc=record.created_at_utc,
        started_at_utc=record.started_at_utc,
        completed_at_utc=record.completed_at_utc,
        stages=[
            ExecutionStageResponse(
                stage_name=stage.stage_name,
                status=stage.status.value,
                started_at_utc=stage.started_at_utc,
                completed_at_utc=stage.completed_at_utc,
                details=stage.details,
                error_message=stage.error_message,
            )
            for stage in record.stages
        ],
    )
