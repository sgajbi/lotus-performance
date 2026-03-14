from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, Field

from app.services.compute_job_store import ComputeQueueStats
from app.services.lineage_metadata_store import LineageQueueStats

if TYPE_CHECKING:
    from app.services.runtime_status_service import RuntimeStatusSnapshot


class DurableMetadataStoreStatusResponse(BaseModel):
    status: str = Field(description="Durable metadata store availability state.")
    reason: str | None = Field(
        default=None,
        description="Concrete degradation reason when the durable metadata store is unavailable.",
    )


class RuntimeDegradationDetailResponse(BaseModel):
    reason: str = Field(description="Concrete degradation trigger identifier.")
    observed_value: float = Field(description="Observed runtime value that breached the configured threshold.")
    threshold_value: float = Field(description="Configured threshold value that was exceeded.")


class ComputeQueueStatusDetailsResponse(BaseModel):
    status: str = Field(description="Compute queue visibility state for the control-plane endpoint.")
    reason: str | None = Field(
        default=None,
        description="Primary compute queue degradation or unavailability reason for simple callers.",
    )
    degradation_reasons: list[str] = Field(
        default_factory=list,
        description="All active compute queue degradation reasons contributing to a degraded state.",
    )
    degradation_details: list[RuntimeDegradationDetailResponse] = Field(
        default_factory=list,
        description="Detailed compute queue degradation triggers with observed and threshold values.",
    )
    pending_jobs: int | None = Field(default=None, description="Number of pending compute jobs awaiting lease.")
    leased_jobs: int | None = Field(default=None, description="Number of compute jobs currently leased by a worker.")
    running_jobs: int | None = Field(default=None, description="Number of compute jobs currently executing.")
    failed_jobs: int | None = Field(default=None, description="Number of compute jobs in terminal failed state.")
    complete_jobs: int | None = Field(
        default=None,
        description="Number of compute jobs completed successfully and still retained durably.",
    )
    retry_backlog_jobs: int | None = Field(
        default=None,
        description="Number of pending compute jobs awaiting another attempt after a prior failure.",
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
        description="Primary lineage queue degradation or unavailability reason for simple callers.",
    )
    degradation_reasons: list[str] = Field(
        default_factory=list,
        description="All active lineage queue degradation reasons contributing to a degraded state.",
    )
    degradation_details: list[RuntimeDegradationDetailResponse] = Field(
        default_factory=list,
        description="Detailed lineage queue degradation triggers with observed and threshold values.",
    )
    pending_payloads: int | None = Field(
        default=None,
        description="Number of pending lineage payloads awaiting worker materialization.",
    )
    retry_backlog_payloads: int | None = Field(
        default=None,
        description="Number of pending lineage payloads awaiting a retry after a prior materialization failure.",
    )
    terminal_failure_payloads: int | None = Field(
        default=None,
        description="Number of lineage payloads that exhausted retry budget and failed terminally.",
    )
    oldest_pending_age_seconds: float | None = Field(
        default=None,
        description="Age in seconds of the oldest pending lineage payload.",
    )


class ComputeQueueDegradationPolicyResponse(BaseModel):
    pending_age_seconds: float = Field(
        description="Configured threshold that degrades runtime on oldest pending compute-job age."
    )
    leased_age_seconds: float = Field(
        description="Configured threshold that degrades runtime on oldest leased compute-job age."
    )
    running_age_seconds: float = Field(
        description="Configured threshold that degrades runtime on oldest running compute-job age."
    )
    retry_backlog_count: int = Field(
        description="Configured threshold that degrades runtime on compute retry-backlog count."
    )
    lease_expiry_count: int = Field(
        description="Configured threshold that degrades runtime on compute lease-expiry recovery count."
    )
    terminal_failure_count: int = Field(
        description="Configured threshold that degrades runtime on compute terminal-failure count."
    )


class LineageQueueDegradationPolicyResponse(BaseModel):
    pending_age_seconds: float = Field(
        description="Configured threshold that degrades runtime on oldest pending lineage-payload age."
    )
    retry_backlog_count: int = Field(
        description="Configured threshold that degrades runtime on lineage retry-backlog count."
    )
    terminal_failure_count: int = Field(
        description="Configured threshold that degrades runtime on lineage terminal-failure count."
    )


class RuntimeStatusResponse(BaseModel):
    contract_version: str = Field(description="Version of the runtime-status response contract.")
    source_service: str = Field(description="Owning service that produced this runtime snapshot.")
    generated_at: datetime = Field(description="Timestamp when the runtime snapshot was generated.")
    runtime_status: str = Field(
        description="Aggregate runtime state for this service: ready, draining, unavailable, or degraded.",
    )
    runtime_degradation_reasons: list[str] = Field(
        default_factory=list,
        description="All active queue-level degradation or unavailability reasons contributing to aggregate runtime status.",
    )
    runtime_degradation_details: list[RuntimeDegradationDetailResponse] = Field(
        default_factory=list,
        description="Detailed active degradation triggers across compute and lineage queues.",
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
    compute_queue_policy: ComputeQueueDegradationPolicyResponse = Field(
        description="Active compute queue degradation policy used to interpret runtime state.",
    )
    lineage_queue_policy: LineageQueueDegradationPolicyResponse = Field(
        description="Active lineage queue degradation policy used to interpret runtime state.",
    )


def _degradation_details_response(details) -> list[RuntimeDegradationDetailResponse]:
    return [
        RuntimeDegradationDetailResponse(
            reason=detail.reason,
            observed_value=detail.observed_value,
            threshold_value=detail.threshold_value,
        )
        for detail in details
    ]


def build_runtime_status_response(snapshot: RuntimeStatusSnapshot) -> RuntimeStatusResponse:
    compute_stats = cast(ComputeQueueStats | None, snapshot.compute_queue.stats)
    lineage_stats = cast(LineageQueueStats | None, snapshot.lineage_queue.stats)

    return RuntimeStatusResponse(
        contract_version="v1",
        source_service="lotus-performance",
        generated_at=snapshot.generated_at,
        runtime_status=snapshot.runtime_status,
        runtime_degradation_reasons=list(snapshot.runtime_degradation_reasons),
        runtime_degradation_details=_degradation_details_response(snapshot.runtime_degradation_details),
        draining=snapshot.draining,
        durable_metadata_store=DurableMetadataStoreStatusResponse(
            status=snapshot.durable_metadata_store.status,
            reason=snapshot.durable_metadata_store.reason,
        ),
        compute_queue=ComputeQueueStatusDetailsResponse(
            status=snapshot.compute_queue.status,
            reason=snapshot.compute_queue.reason,
            degradation_reasons=list(snapshot.compute_queue.degradation_reasons),
            degradation_details=_degradation_details_response(snapshot.compute_queue.degradation_details),
            pending_jobs=None if compute_stats is None else compute_stats.pending_count,
            leased_jobs=None if compute_stats is None else compute_stats.leased_count,
            running_jobs=None if compute_stats is None else compute_stats.running_count,
            failed_jobs=None if compute_stats is None else compute_stats.failed_count,
            complete_jobs=None if compute_stats is None else compute_stats.complete_count,
            retry_backlog_jobs=None if compute_stats is None else compute_stats.retry_backlog_count,
            lease_expired_jobs=None if compute_stats is None else compute_stats.lease_expired_count,
            terminal_failure_jobs=None if compute_stats is None else compute_stats.terminal_failure_count,
            oldest_pending_age_seconds=None if compute_stats is None else compute_stats.oldest_pending_age_seconds,
            oldest_leased_age_seconds=None if compute_stats is None else compute_stats.oldest_leased_age_seconds,
            oldest_running_age_seconds=None if compute_stats is None else compute_stats.oldest_running_age_seconds,
        ),
        lineage_queue=LineageQueueStatusDetailsResponse(
            status=snapshot.lineage_queue.status,
            reason=snapshot.lineage_queue.reason,
            degradation_reasons=list(snapshot.lineage_queue.degradation_reasons),
            degradation_details=_degradation_details_response(snapshot.lineage_queue.degradation_details),
            pending_payloads=None if lineage_stats is None else lineage_stats.pending_payload_count,
            retry_backlog_payloads=None if lineage_stats is None else lineage_stats.retry_backlog_count,
            terminal_failure_payloads=None if lineage_stats is None else lineage_stats.terminal_failure_count,
            oldest_pending_age_seconds=None if lineage_stats is None else lineage_stats.oldest_pending_age_seconds,
        ),
        compute_queue_policy=ComputeQueueDegradationPolicyResponse(
            pending_age_seconds=snapshot.compute_queue_policy.pending_age_seconds,
            leased_age_seconds=snapshot.compute_queue_policy.leased_age_seconds,
            running_age_seconds=snapshot.compute_queue_policy.running_age_seconds,
            retry_backlog_count=snapshot.compute_queue_policy.retry_backlog_count,
            lease_expiry_count=snapshot.compute_queue_policy.lease_expiry_count,
            terminal_failure_count=snapshot.compute_queue_policy.terminal_failure_count,
        ),
        lineage_queue_policy=LineageQueueDegradationPolicyResponse(
            pending_age_seconds=snapshot.lineage_queue_policy.pending_age_seconds,
            retry_backlog_count=snapshot.lineage_queue_policy.retry_backlog_count,
            terminal_failure_count=snapshot.lineage_queue_policy.terminal_failure_count,
        ),
    )
