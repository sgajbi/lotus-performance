from __future__ import annotations

from uuid import UUID

from fastapi.responses import JSONResponse

from app.models.execution_polling import (
    AsyncResultResponse,
    ComputeJobResponse,
    ExecutionResponse,
    ExecutionStageResponse,
    UpstreamSnapshotResponse,
)
from app.services.async_result_store import AsyncResultRecord, async_result_store
from app.services.calculation_result_access import authorize_calculation_result_access
from app.services.compute_job_store import ComputeJobRecord, compute_job_store
from app.services.execution_registry import (
    ExecutionRecord,
    ExecutionStageRecord,
    UpstreamSnapshotRecord,
    execution_registry,
)

EXECUTION_POLLING_NOT_FOUND_DETAIL = "Execution data not found for the given calculation_id."


def get_execution_polling_response(
    calculation_id: UUID, *, request_headers=None
) -> ExecutionResponse | JSONResponse | None:
    record = execution_registry.get_execution(calculation_id)
    if record is None:
        return None
    access_denial = authorize_calculation_result_access(execution=record, headers=request_headers)
    if access_denial is not None:
        return access_denial
    return build_execution_response(
        record=record,
        job=compute_job_store.get_job(calculation_id),
        async_result=async_result_store.get_result(calculation_id),
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
        stages=[_stage_response(stage) for stage in record.stages],
        upstream_snapshots=[_upstream_snapshot_response(snapshot) for snapshot in record.upstream_snapshots],
        compute_job=_compute_job_response(job),
        async_result=_async_result_response(async_result),
    )


def _stage_response(stage: ExecutionStageRecord) -> ExecutionStageResponse:
    return ExecutionStageResponse(
        stage_name=stage.stage_name,
        status=stage.status.value,
        started_at_utc=stage.started_at_utc,
        completed_at_utc=stage.completed_at_utc,
        details=stage.details,
        error_message=stage.error_message,
    )


def _upstream_snapshot_response(snapshot: UpstreamSnapshotRecord) -> UpstreamSnapshotResponse:
    return UpstreamSnapshotResponse(
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


def _async_result_response(async_result: AsyncResultRecord | None) -> AsyncResultResponse | None:
    if async_result is None:
        return None
    return AsyncResultResponse(
        result_status=async_result.result_status.value,
        error_message=async_result.error_message,
        error_type=async_result.error_type,
        created_at_utc=async_result.created_at_utc,
        updated_at_utc=async_result.updated_at_utc,
    )
