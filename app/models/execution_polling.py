from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.async_result_store import AsyncResultRecord
from app.services.compute_job_store import ComputeJobRecord
from app.services.execution_registry import ExecutionRecord


class ExecutionStageResponse(BaseModel):
    stage_name: str = Field(
        description="Stable execution stage name within the calculation lifecycle.",
        examples=["execution"],
    )
    status: str = Field(
        description="Current stage status. Typical values are pending, in_progress, complete, and failed.",
        examples=["complete"],
    )
    started_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp when this stage started, or null if it has not started.",
        examples=["2026-04-10T12:00:01Z"],
    )
    completed_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp when this stage completed, or null while it is pending or running.",
        examples=["2026-04-10T12:00:02Z"],
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Stage-specific metadata such as observation counts, chunk counts, or materialized artifact names.",
        examples=[{"portfolio_observations": 3, "portfolio_chunk_count": 1, "portfolio_page_count": 1}],
    )
    error_message: str | None = Field(
        default=None,
        description="Stage-level failure detail when this stage failed.",
        examples=["temporary upstream issue"],
    )


class UpstreamSnapshotResponse(BaseModel):
    snapshot_id: str = Field(
        description="Durable upstream snapshot identifier recorded for this calculation.",
        examples=["portfolio_timeseries:PB_SG_GLOBAL_BAL_001:2026-04-10"],
    )
    upstream_endpoint: str = Field(
        description="Canonical upstream contract family or endpoint that produced the snapshot.",
        examples=["portfolio_timeseries"],
    )
    source_identifier: str = Field(
        description="Portfolio, benchmark, index, or source identifier used for upstream retrieval.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    as_of_date: str = Field(
        description="Business date associated with the upstream snapshot.",
        examples=["2026-04-10"],
    )
    request_fingerprint: str = Field(
        description="Stable fingerprint of the upstream request payload.",
        examples=["sha256:request-fingerprint"],
    )
    response_fingerprint: str = Field(
        description="Stable fingerprint of the upstream response payload.",
        examples=["sha256:response-fingerprint"],
    )
    retrieval_status: str = Field(
        description="Upstream retrieval outcome, usually the HTTP status code or governed retrieval state.",
        examples=["200"],
    )
    paging_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional paging or chunking metadata captured during upstream retrieval.",
        examples=[{"chunk_count": 1, "page_count": 1}],
    )
    created_at_utc: str = Field(
        description="UTC timestamp when lotus-performance recorded this upstream snapshot.",
        examples=["2026-04-10T12:00:00Z"],
    )


class ComputeJobResponse(BaseModel):
    job_status: str = Field(
        description="Durable compute-job status for async executor-backed work.",
        examples=["pending"],
    )
    attempt_count: int = Field(
        description="Number of compute execution attempts already consumed.",
        examples=[1],
    )
    max_attempts: int = Field(
        description="Maximum compute attempts allowed before the job becomes terminally failed.",
        examples=[3],
    )
    worker_id: str | None = Field(
        default=None,
        description="Identifier of the worker currently or most recently processing the job.",
        examples=["performance-compute-executor-1"],
    )
    error_message: str | None = Field(
        default=None,
        description="Most recent compute failure message when retryable or terminal failure occurred.",
        examples=["temporary upstream issue"],
    )
    error_type: str | None = Field(
        default=None,
        description="Most recent compute failure class or governed error type.",
        examples=["HTTPException"],
    )
    leased_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp when a worker leased the job, or null when the job is not leased.",
        examples=["2026-04-10T12:00:03Z"],
    )
    lease_expires_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp when the current worker lease expires.",
        examples=["2026-04-10T12:05:03Z"],
    )
    last_error_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp of the most recent compute error.",
        examples=["2026-04-10T12:00:04Z"],
    )
    created_at_utc: str = Field(
        description="UTC timestamp when the compute job was created.",
        examples=["2026-04-10T12:00:00Z"],
    )
    started_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp when compute execution started.",
        examples=["2026-04-10T12:00:03Z"],
    )
    completed_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp when compute execution completed.",
        examples=["2026-04-10T12:00:08Z"],
    )


class AsyncResultResponse(BaseModel):
    result_status: str = Field(
        description="Durable async-result status for endpoint-specific result retrieval.",
        examples=["complete"],
    )
    error_message: str | None = Field(
        default=None,
        description="Terminal async-result failure message, if result materialization failed.",
        examples=["explode"],
    )
    error_type: str | None = Field(
        default=None,
        description="Terminal async-result failure class or governed error type.",
        examples=["RuntimeError"],
    )
    created_at_utc: str = Field(
        description="UTC timestamp when the async-result record was created.",
        examples=["2026-04-10T12:00:06Z"],
    )
    updated_at_utc: str = Field(
        description="UTC timestamp when the async-result record was last updated.",
        examples=["2026-04-10T12:00:08Z"],
    )


class ExecutionResponse(BaseModel):
    calculation_id: UUID = Field(
        description="Durable calculation handle returned by the originating sync or async endpoint.",
        examples=["2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"],
    )
    analytics_type: str = Field(
        description="Analytics family associated with this execution.",
        examples=["TWR"],
    )
    portfolio_id: str | None = Field(
        default=None,
        description="Portfolio identifier when the calculation is portfolio-scoped.",
        examples=["PB_SG_GLOBAL_BAL_001"],
    )
    execution_mode: str = Field(
        description="Whether the calculation ran inline or through the async compute executor.",
        examples=["async"],
    )
    status: str = Field(
        description="Overall execution lifecycle status. Typical values are pending, running, complete, and failed.",
        examples=["complete"],
    )
    requested_window: dict[str, Any] = Field(
        description="Normalized request-window metadata captured for operator and downstream polling.",
        examples=[{"start_date": "2026-01-01", "end_date": "2026-04-10", "input_count": 100}],
    )
    input_fingerprint: str | None = Field(
        default=None,
        description="Stable fingerprint of the submitted or resolved calculation input.",
        examples=["sha256:input-fingerprint"],
    )
    calculation_hash: str | None = Field(
        default=None,
        description="Stable hash of completed calculation output when available.",
        examples=["sha256:calculation-output"],
    )
    error_message: str | None = Field(
        default=None,
        description="Top-level execution failure message when the calculation failed.",
        examples=["No benchmark assignment found for portfolio."],
    )
    created_at_utc: str = Field(
        description="UTC timestamp when the execution record was created.",
        examples=["2026-04-10T12:00:00Z"],
    )
    started_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp when execution started.",
        examples=["2026-04-10T12:00:01Z"],
    )
    completed_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp when execution reached a terminal state.",
        examples=["2026-04-10T12:00:08Z"],
    )
    stages: list[ExecutionStageResponse] = Field(
        description="Ordered stage-level lifecycle records for retrieval, normalization, execution, lineage, or submission.",
    )
    upstream_snapshots: list[UpstreamSnapshotResponse] = Field(
        description="Durable upstream source snapshots captured during stateful calculation sourcing.",
    )
    compute_job: ComputeJobResponse | None = Field(
        default=None,
        description="Async compute-job metadata when this execution used the compute executor.",
    )
    async_result: AsyncResultResponse | None = Field(
        default=None,
        description="Endpoint-specific async result metadata when a durable result record exists.",
    )


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
        compute_job=_compute_job_response(job),
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


def _compute_job_response(job: ComputeJobRecord | None) -> ComputeJobResponse | None:
    if job is None:
        return None
    return ComputeJobResponse(
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
