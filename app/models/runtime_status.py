from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, cast

from pydantic import BaseModel, Field, PlainSerializer

from app.services.compute_job_store import ComputeQueueInspectionAnchors, ComputeQueueStats, ComputeRecoveryEvent
from app.services.lineage_metadata_store import LineageQueueInspectionAnchors, LineageQueueStats, LineageRecoveryEvent

if TYPE_CHECKING:
    from app.services.runtime_status_service import RuntimeStatusSnapshot


DegradationNumeric = Annotated[Decimal, PlainSerializer(lambda v: float(v))]


class DurableMetadataStoreStatusResponse(BaseModel):
    status: str = Field(description="Durable metadata store availability state.")
    reason: str | None = Field(
        default=None,
        description="Concrete degradation reason when the durable metadata store is unavailable.",
    )


class RuntimeDegradationDetailResponse(BaseModel):
    reason: str = Field(description="Concrete degradation trigger identifier.")
    observed_value: DegradationNumeric = Field(
        description="Observed runtime value that breached the configured threshold."
    )
    threshold_value: DegradationNumeric = Field(description="Configured threshold value that was exceeded.")


class ComputeQueueInspectionAnchorsResponse(BaseModel):
    oldest_pending_calculation_id: str | None = Field(
        default=None,
        description="Calculation handle of the oldest pending compute job, if one exists.",
    )
    oldest_leased_calculation_id: str | None = Field(
        default=None,
        description="Calculation handle of the oldest leased compute job, if one exists.",
    )
    oldest_running_calculation_id: str | None = Field(
        default=None,
        description="Calculation handle of the oldest running compute job, if one exists.",
    )
    latest_terminal_failure_calculation_id: str | None = Field(
        default=None,
        description="Calculation handle of the most recently terminally failed compute job, if one exists.",
    )
    latest_recovered_calculation_id: str | None = Field(
        default=None,
        description="Calculation handle of the most recently requeued compute job after retry or stale-lease recovery, if one exists.",
    )


class LineageQueueInspectionAnchorsResponse(BaseModel):
    oldest_pending_calculation_id: str | None = Field(
        default=None,
        description="Calculation handle of the oldest pending lineage payload, if one exists.",
    )
    oldest_leased_calculation_id: str | None = Field(
        default=None,
        description="Calculation handle of the oldest leased lineage payload, if one exists.",
    )
    latest_terminal_failure_calculation_id: str | None = Field(
        default=None,
        description="Calculation handle of the most recently terminally failed lineage item, if one exists.",
    )
    latest_recovered_calculation_id: str | None = Field(
        default=None,
        description="Calculation handle of the most recently requeued lineage item after a retryable materialization failure, if one exists.",
    )


class ComputeRecoveryEventResponse(BaseModel):
    calculation_id: str = Field(description="Calculation handle of the recovered compute job.")
    analytics_type: str = Field(description="Analytics workflow type for the recovered compute job.")
    recovery_kind: str = Field(description="Recovery path that returned the compute job to pending state.")
    recovered_at_utc: str = Field(description="UTC timestamp when the compute job most recently re-entered pending state.")
    attempt_count: int = Field(description="Attempt count already consumed by the recovered compute job.")
    error_type: str | None = Field(
        default=None,
        description="Last durable compute error type associated with the recovery event, when present.",
    )


class LineageRecoveryEventResponse(BaseModel):
    calculation_id: str = Field(description="Calculation handle of the recovered lineage item.")
    calculation_type: str = Field(description="Analytics workflow type for the recovered lineage item.")
    recovery_kind: str = Field(description="Recovery path that returned the lineage item to pending state.")
    recovered_at_utc: str = Field(description="UTC timestamp when the lineage item most recently re-entered pending state.")
    attempt_count: int = Field(description="Attempt count already consumed by the recovered lineage item.")


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
    reclaimable_jobs: int | None = Field(
        default=None,
        description="Number of compute jobs whose durable worker lease already expired and are eligible for recovery.",
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
    inspection_anchors: ComputeQueueInspectionAnchorsResponse | None = Field(
        default=None,
        description="Concrete calculation handles for the current oldest or most recent compute work items of operator interest.",
    )
    recent_recoveries: list[ComputeRecoveryEventResponse] = Field(
        default_factory=list,
        description="Most recent durable compute recovery events returned to pending state for operator triage.",
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
    leased_payloads: int | None = Field(
        default=None,
        description="Number of lineage payloads currently claimed by a worker for materialization.",
    )
    retry_backlog_payloads: int | None = Field(
        default=None,
        description="Number of pending lineage payloads awaiting a retry after a prior materialization failure.",
    )
    terminal_failure_payloads: int | None = Field(
        default=None,
        description="Number of lineage payloads that exhausted retry budget and failed terminally.",
    )
    reclaimable_payloads: int | None = Field(
        default=None,
        description="Number of pending lineage payloads whose durable worker lease already expired and are eligible for recovery.",
    )
    oldest_pending_age_seconds: float | None = Field(
        default=None,
        description="Age in seconds of the oldest pending lineage payload.",
    )
    oldest_leased_age_seconds: float | None = Field(
        default=None,
        description="Age in seconds of the oldest claimed lineage payload still in progress.",
    )
    inspection_anchors: LineageQueueInspectionAnchorsResponse | None = Field(
        default=None,
        description="Concrete calculation handles for the current oldest or most recent lineage work items of operator interest.",
    )
    recent_recoveries: list[LineageRecoveryEventResponse] = Field(
        default_factory=list,
        description="Most recent durable lineage recovery events returned to pending state for operator triage.",
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
    leased_age_seconds: float = Field(
        description="Configured threshold that degrades runtime on oldest claimed lineage-payload age."
    )
    retry_backlog_count: int = Field(
        description="Configured threshold that degrades runtime on lineage retry-backlog count."
    )
    terminal_failure_count: int = Field(
        description="Configured threshold that degrades runtime on lineage terminal-failure count."
    )


class RecoveryDrillStatusResponse(BaseModel):
    status: str = Field(description="Recovery-drill assurance status for the current retained control-plane history.")
    reason: str | None = Field(
        default=None,
        description="Primary recovery-drill degradation or unavailability reason for simple callers.",
    )
    degradation_reasons: list[str] = Field(
        default_factory=list,
        description="All active recovery-drill degradation reasons contributing to a degraded state.",
    )
    degradation_details: list[RuntimeDegradationDetailResponse] = Field(
        default_factory=list,
        description="Detailed recovery-drill degradation triggers with observed and threshold values.",
    )
    latest_generated_at_utc: str | None = Field(
        default=None,
        description="UTC timestamp of the latest retained recovery drill.",
    )
    latest_status: str | None = Field(
        default=None,
        description="Outcome status of the latest retained recovery drill.",
    )
    latest_operator_id: str | None = Field(
        default=None,
        description="Operator or automation identity that ran the latest retained recovery drill.",
    )
    latest_backup_identifier: str | None = Field(
        default=None,
        description="Backup or restore-set identifier validated by the latest retained recovery drill.",
    )
    latest_age_seconds: float | None = Field(
        default=None,
        description="Age in seconds of the latest retained recovery drill.",
    )


class RecoveryDrillDegradationPolicyResponse(BaseModel):
    max_age_seconds: float = Field(
        description="Configured threshold that degrades runtime when the latest retained recovery drill is too old."
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
    recovery_drill: RecoveryDrillStatusResponse = Field(
        description="Current retained recovery-drill assurance status for operational recovery proof.",
    )
    compute_queue_policy: ComputeQueueDegradationPolicyResponse = Field(
        description="Active compute queue degradation policy used to interpret runtime state.",
    )
    lineage_queue_policy: LineageQueueDegradationPolicyResponse = Field(
        description="Active lineage queue degradation policy used to interpret runtime state.",
    )
    recovery_drill_policy: RecoveryDrillDegradationPolicyResponse = Field(
        description="Active recovery-drill freshness policy used to interpret runtime state.",
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
    compute_anchors = cast(ComputeQueueInspectionAnchors | None, snapshot.compute_queue.inspection_anchors)
    lineage_anchors = cast(LineageQueueInspectionAnchors | None, snapshot.lineage_queue.inspection_anchors)
    compute_recoveries = cast(tuple[ComputeRecoveryEvent, ...], snapshot.compute_queue.recent_recoveries)
    lineage_recoveries = cast(tuple[LineageRecoveryEvent, ...], snapshot.lineage_queue.recent_recoveries)

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
            reclaimable_jobs=None if compute_stats is None else compute_stats.reclaimable_count,
            terminal_failure_jobs=None if compute_stats is None else compute_stats.terminal_failure_count,
            oldest_pending_age_seconds=None if compute_stats is None else compute_stats.oldest_pending_age_seconds,
            oldest_leased_age_seconds=None if compute_stats is None else compute_stats.oldest_leased_age_seconds,
            oldest_running_age_seconds=None if compute_stats is None else compute_stats.oldest_running_age_seconds,
            inspection_anchors=(
                None
                if compute_anchors is None
                else ComputeQueueInspectionAnchorsResponse(
                    oldest_pending_calculation_id=compute_anchors.oldest_pending_calculation_id,
                    oldest_leased_calculation_id=compute_anchors.oldest_leased_calculation_id,
                    oldest_running_calculation_id=compute_anchors.oldest_running_calculation_id,
                    latest_terminal_failure_calculation_id=compute_anchors.latest_terminal_failure_calculation_id,
                    latest_recovered_calculation_id=compute_anchors.latest_recovered_calculation_id,
                )
            ),
            recent_recoveries=[
                ComputeRecoveryEventResponse(
                    calculation_id=item.calculation_id,
                    analytics_type=item.analytics_type,
                    recovery_kind=item.recovery_kind,
                    recovered_at_utc=item.recovered_at_utc,
                    attempt_count=item.attempt_count,
                    error_type=item.error_type,
                )
                for item in compute_recoveries
            ],
        ),
        lineage_queue=LineageQueueStatusDetailsResponse(
            status=snapshot.lineage_queue.status,
            reason=snapshot.lineage_queue.reason,
            degradation_reasons=list(snapshot.lineage_queue.degradation_reasons),
            degradation_details=_degradation_details_response(snapshot.lineage_queue.degradation_details),
            pending_payloads=None if lineage_stats is None else lineage_stats.pending_payload_count,
            leased_payloads=None if lineage_stats is None else lineage_stats.leased_payload_count,
            retry_backlog_payloads=None if lineage_stats is None else lineage_stats.retry_backlog_count,
            reclaimable_payloads=None if lineage_stats is None else lineage_stats.reclaimable_count,
            terminal_failure_payloads=None if lineage_stats is None else lineage_stats.terminal_failure_count,
            oldest_pending_age_seconds=None if lineage_stats is None else lineage_stats.oldest_pending_age_seconds,
            oldest_leased_age_seconds=None if lineage_stats is None else lineage_stats.oldest_leased_age_seconds,
            inspection_anchors=(
                None
                if lineage_anchors is None
                else LineageQueueInspectionAnchorsResponse(
                    oldest_pending_calculation_id=lineage_anchors.oldest_pending_calculation_id,
                    oldest_leased_calculation_id=lineage_anchors.oldest_leased_calculation_id,
                    latest_terminal_failure_calculation_id=lineage_anchors.latest_terminal_failure_calculation_id,
                    latest_recovered_calculation_id=lineage_anchors.latest_recovered_calculation_id,
                )
            ),
            recent_recoveries=[
                LineageRecoveryEventResponse(
                    calculation_id=item.calculation_id,
                    calculation_type=item.calculation_type,
                    recovery_kind=item.recovery_kind,
                    recovered_at_utc=item.recovered_at_utc,
                    attempt_count=item.attempt_count,
                )
                for item in lineage_recoveries
            ],
        ),
        recovery_drill=RecoveryDrillStatusResponse(
            status=snapshot.recovery_drill.status,
            reason=snapshot.recovery_drill.reason,
            degradation_reasons=list(snapshot.recovery_drill.degradation_reasons),
            degradation_details=_degradation_details_response(snapshot.recovery_drill.degradation_details),
            latest_generated_at_utc=snapshot.recovery_drill.latest_generated_at_utc,
            latest_status=snapshot.recovery_drill.latest_status,
            latest_operator_id=snapshot.recovery_drill.latest_operator_id,
            latest_backup_identifier=snapshot.recovery_drill.latest_backup_identifier,
            latest_age_seconds=snapshot.recovery_drill.latest_age_seconds,
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
            leased_age_seconds=snapshot.lineage_queue_policy.leased_age_seconds,
            retry_backlog_count=snapshot.lineage_queue_policy.retry_backlog_count,
            terminal_failure_count=snapshot.lineage_queue_policy.terminal_failure_count,
        ),
        recovery_drill_policy=RecoveryDrillDegradationPolicyResponse(
            max_age_seconds=snapshot.recovery_drill_policy.max_age_seconds,
        ),
    )
