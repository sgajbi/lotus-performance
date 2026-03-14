from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.async_result_store import AsyncResultRecord
from app.services.compute_job_store import ComputeJobRecord
from app.services.execution_registry import ExecutionRecord


class ExecutionStageResponse(BaseModel):
    stage_name: str = Field(description="Internal execution stage name.")
    status: str = Field(description="Current stage status.")
    started_at_utc: str | None = Field(default=None, description="UTC timestamp when the stage started.")
    completed_at_utc: str | None = Field(default=None, description="UTC timestamp when the stage completed.")
    details: dict[str, Any] | None = Field(default=None, description="Optional stage metadata details.")
    error_message: str | None = Field(default=None, description="Failure detail if the stage failed.")


class UpstreamSnapshotResponse(BaseModel):
    snapshot_id: str
    upstream_endpoint: str
    source_identifier: str
    as_of_date: str
    request_fingerprint: str
    response_fingerprint: str
    retrieval_status: str
    paging_metadata: dict[str, Any] | None = None
    created_at_utc: str


class ComputeJobResponse(BaseModel):
    job_status: str
    attempt_count: int
    max_attempts: int
    worker_id: str | None = None
    error_message: str | None = None
    error_type: str | None = None
    leased_at_utc: str | None = None
    lease_expires_at_utc: str | None = None
    last_error_at_utc: str | None = None
    created_at_utc: str
    started_at_utc: str | None = None
    completed_at_utc: str | None = None


class AsyncResultResponse(BaseModel):
    result_status: str
    error_message: str | None = None
    error_type: str | None = None
    created_at_utc: str
    updated_at_utc: str


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
    upstream_snapshots: list[UpstreamSnapshotResponse]
    compute_job: ComputeJobResponse | None = None
    async_result: AsyncResultResponse | None = None


def build_execution_response(
    *,
    record: ExecutionRecord,
    job: ComputeJobRecord | None,
    async_result: AsyncResultRecord | None,
) -> ExecutionResponse:
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
        upstream_snapshots=[
            UpstreamSnapshotResponse(
                snapshot_id=snapshot.snapshot_id,
                upstream_endpoint=snapshot.upstream_endpoint,
                source_identifier=snapshot.source_identifier,
                as_of_date=snapshot.as_of_date,
                request_fingerprint=snapshot.request_fingerprint,
                response_fingerprint=snapshot.response_fingerprint,
                retrieval_status=snapshot.retrieval_status,
                paging_metadata=snapshot.paging_metadata,
                created_at_utc=snapshot.created_at_utc,
            )
            for snapshot in record.upstream_snapshots
        ],
        compute_job=(
            None
            if job is None
            else ComputeJobResponse(
                job_status=job.job_status.value,
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                worker_id=job.worker_id,
                error_message=job.error_message,
                error_type=job.error_type,
                leased_at_utc=job.leased_at_utc,
                lease_expires_at_utc=job.lease_expires_at_utc,
                last_error_at_utc=job.last_error_at_utc,
                created_at_utc=job.created_at_utc,
                started_at_utc=job.started_at_utc,
                completed_at_utc=job.completed_at_utc,
            )
        ),
        async_result=(
            None
            if async_result is None
            else AsyncResultResponse(
                result_status=async_result.result_status.value,
                error_message=async_result.error_message,
                error_type=async_result.error_type,
                created_at_utc=async_result.created_at_utc,
                updated_at_utc=async_result.updated_at_utc,
            )
        ),
    )
