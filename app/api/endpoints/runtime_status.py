from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.services.compute_job_store import ComputeQueueStats
from app.services.lineage_metadata_store import LineageQueueStats
from app.services.runtime_status_service import build_runtime_status_snapshot

router = APIRouter(tags=["Integration"])


class DurableMetadataStoreStatusResponse(BaseModel):
    status: str = Field(description="Durable metadata store availability state.")
    reason: str | None = Field(
        default=None,
        description="Concrete degradation reason when the durable metadata store is unavailable.",
    )


class ComputeQueueStatusDetailsResponse(BaseModel):
    status: str = Field(description="Compute queue visibility state for the control-plane endpoint.")
    reason: str | None = Field(
        default=None,
        description="Reason compute queue details are unavailable.",
    )
    pending_jobs: int | None = Field(
        default=None,
        description="Number of pending compute jobs awaiting lease.",
    )
    leased_jobs: int | None = Field(
        default=None,
        description="Number of compute jobs currently leased by a worker.",
    )
    running_jobs: int | None = Field(
        default=None,
        description="Number of compute jobs currently executing.",
    )
    failed_jobs: int | None = Field(
        default=None,
        description="Number of compute jobs in terminal failed state.",
    )
    complete_jobs: int | None = Field(
        default=None,
        description="Number of compute jobs completed successfully and still retained durably.",
    )
    retry_backlog_jobs: int | None = Field(
        default=None,
        description="Number of pending compute jobs that are awaiting another attempt after a prior failure.",
    )
    lease_expired_jobs: int | None = Field(
        default=None,
        description="Number of compute jobs carrying expired-lease recovery state.",
    )
    terminal_failure_jobs: int | None = Field(
        default=None,
        description="Number of compute jobs that failed terminally for non-lease-expiry reasons.",
    )
    oldest_pending_age_seconds: float | None = Field(
        default=None,
        description="Age in seconds of the oldest pending compute job.",
    )
    oldest_leased_age_seconds: float | None = Field(
        default=None,
        description="Age in seconds of the oldest leased compute job awaiting worker progress.",
    )
    oldest_running_age_seconds: float | None = Field(
        default=None,
        description="Age in seconds of the oldest running compute job currently executing.",
    )


class LineageQueueStatusDetailsResponse(BaseModel):
    status: str = Field(description="Lineage queue visibility state for the control-plane endpoint.")
    reason: str | None = Field(
        default=None,
        description="Reason lineage queue details are unavailable.",
    )
    pending_payloads: int | None = Field(
        default=None,
        description="Number of pending lineage payloads awaiting worker materialization.",
    )
    oldest_pending_age_seconds: float | None = Field(
        default=None,
        description="Age in seconds of the oldest pending lineage payload.",
    )


class RuntimeStatusResponse(BaseModel):
    contract_version: str = Field(description="Version of the runtime-status response contract.")
    source_service: str = Field(description="Owning service that produced this runtime snapshot.")
    generated_at: datetime = Field(description="Timestamp when the runtime snapshot was generated.")
    runtime_status: str = Field(
        description="Aggregate runtime state for this service: ready, draining, unavailable, or degraded.",
    )
    draining: bool = Field(description="Whether the API process is intentionally draining traffic.")
    durable_metadata_store: DurableMetadataStoreStatusResponse = Field(
        description="Availability of the durable metadata store that backs execution and lineage state.",
    )
    compute_queue: ComputeQueueStatusDetailsResponse = Field(
        description="Current durable compute queue state for executor-backed analytics work.",
    )
    lineage_queue: LineageQueueStatusDetailsResponse = Field(
        description="Current durable lineage queue state for asynchronous lineage artifact materialization.",
    )


@router.get(
    "/runtime-status",
    response_model=RuntimeStatusResponse,
    summary="Get lotus-performance runtime status",
    description=(
        "Returns an operational snapshot of lotus-performance durable runtime state, including draining status, "
        "durable metadata store availability, and current compute and lineage queue backlog details."
    ),
)
async def get_runtime_status(request: Request) -> RuntimeStatusResponse:
    snapshot = build_runtime_status_snapshot(is_draining=bool(getattr(request.app.state, "is_draining", False)))
    compute_stats = cast(ComputeQueueStats | None, snapshot.compute_queue.stats)
    lineage_stats = cast(LineageQueueStats | None, snapshot.lineage_queue.stats)

    return RuntimeStatusResponse(
        contract_version="v1",
        source_service="lotus-performance",
        generated_at=snapshot.generated_at,
        runtime_status=snapshot.runtime_status,
        draining=snapshot.draining,
        durable_metadata_store=DurableMetadataStoreStatusResponse(
            status=snapshot.durable_metadata_store.status,
            reason=snapshot.durable_metadata_store.reason,
        ),
        compute_queue=ComputeQueueStatusDetailsResponse(
            status=snapshot.compute_queue.status,
            reason=snapshot.compute_queue.reason,
            pending_jobs=None if compute_stats is None else compute_stats.pending_count,
            leased_jobs=None if compute_stats is None else compute_stats.leased_count,
            running_jobs=None if compute_stats is None else compute_stats.running_count,
            failed_jobs=None if compute_stats is None else compute_stats.failed_count,
            complete_jobs=None if compute_stats is None else compute_stats.complete_count,
            retry_backlog_jobs=None if compute_stats is None else compute_stats.retry_backlog_count,
            lease_expired_jobs=None if compute_stats is None else compute_stats.lease_expired_count,
            terminal_failure_jobs=None if compute_stats is None else compute_stats.terminal_failure_count,
            oldest_pending_age_seconds=(None if compute_stats is None else compute_stats.oldest_pending_age_seconds),
            oldest_leased_age_seconds=(None if compute_stats is None else compute_stats.oldest_leased_age_seconds),
            oldest_running_age_seconds=(None if compute_stats is None else compute_stats.oldest_running_age_seconds),
        ),
        lineage_queue=LineageQueueStatusDetailsResponse(
            status=snapshot.lineage_queue.status,
            reason=snapshot.lineage_queue.reason,
            pending_payloads=None if lineage_stats is None else lineage_stats.pending_payload_count,
            oldest_pending_age_seconds=(None if lineage_stats is None else lineage_stats.oldest_pending_age_seconds),
        ),
    )
