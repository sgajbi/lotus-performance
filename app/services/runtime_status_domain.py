from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.services.compute_job_store import (
    ComputeQueueInspectionAnchors,
    ComputeQueueStats,
    ComputeRecoveryEvent,
)
from app.services.durability_health_service import DurabilityHealthStatus, LineageStorageCapacitySnapshot
from app.services.lineage_metadata_store import (
    LineageQueueInspectionAnchors,
    LineageQueueStats,
    LineageRecoveryEvent,
)


@dataclass(frozen=True)
class RuntimeQueueStatus:
    status: str
    reason: str | None
    degradation_reasons: tuple[str, ...]
    degradation_details: tuple["RuntimeDegradationDetail", ...]
    stats: ComputeQueueStats | LineageQueueStats | None
    inspection_anchors: ComputeQueueInspectionAnchors | LineageQueueInspectionAnchors | None
    recent_recoveries: tuple[ComputeRecoveryEvent | LineageRecoveryEvent, ...]
    storage_capacity: LineageStorageCapacitySnapshot | None = None


@dataclass(frozen=True)
class RuntimeDegradationDetail:
    reason: str
    observed_value: Decimal
    threshold_value: Decimal


@dataclass(frozen=True)
class ComputeQueueDegradationPolicy:
    pending_age_seconds: float
    leased_age_seconds: float
    running_age_seconds: float
    retry_backlog_count: int
    lease_expiry_count: int
    terminal_failure_count: int


@dataclass(frozen=True)
class LineageQueueDegradationPolicy:
    pending_age_seconds: float
    leased_age_seconds: float
    retry_backlog_count: int
    terminal_failure_count: int
    storage_min_free_bytes: int
    storage_min_free_ratio: float


@dataclass(frozen=True)
class RecoveryDrillStatus:
    status: str
    reason: str | None
    active_run_status: str
    active_run_reason: str | None
    active_run_count: int
    oldest_active_run_operator_id: str | None
    oldest_active_run_tenant_id: str | None
    oldest_active_run_governed_target: str | None
    oldest_active_run_acquired_at_utc: str | None
    oldest_active_run_age_seconds: float | None
    latest_reclaimed_run_operator_id: str | None
    latest_reclaimed_run_tenant_id: str | None
    latest_reclaimed_run_governed_target: str | None
    latest_reclaimed_run_acquired_at_utc: str | None
    latest_reclaimed_run_reclaimed_at_utc: str | None
    latest_reclaimed_run_age_seconds: float | None
    reclaimed_run_count: int
    recent_reclaimed_runs: tuple["RecentOperatorActionReclaim", ...]
    latest_generated_at_utc: str | None
    latest_status: str | None
    latest_operator_id: str | None
    latest_backup_identifier: str | None
    latest_age_seconds: float | None
    degradation_reasons: tuple[str, ...]
    degradation_details: tuple["RuntimeDegradationDetail", ...]


@dataclass(frozen=True)
class RecoveryDrillDegradationPolicy:
    max_age_seconds: float
    active_run_age_seconds: float
    reclaim_count: int


@dataclass(frozen=True)
class RuntimeRetentionStatus:
    status: str
    reason: str | None
    active_run_status: str
    active_run_reason: str | None
    active_run_count: int
    oldest_active_run_operator_id: str | None
    oldest_active_run_tenant_id: str | None
    oldest_active_run_governed_target: str | None
    oldest_active_run_acquired_at_utc: str | None
    oldest_active_run_age_seconds: float | None
    latest_reclaimed_run_operator_id: str | None
    latest_reclaimed_run_tenant_id: str | None
    latest_reclaimed_run_governed_target: str | None
    latest_reclaimed_run_acquired_at_utc: str | None
    latest_reclaimed_run_reclaimed_at_utc: str | None
    latest_reclaimed_run_age_seconds: float | None
    reclaimed_run_count: int
    recent_reclaimed_runs: tuple["RecentOperatorActionReclaim", ...]
    preview_status: str
    preview_reason: str | None
    current_cutoff_utc: str | None
    current_retention_days: int | None
    current_prunable_execution_count: int | None
    current_prunable_compute_job_count: int | None
    current_prunable_async_result_count: int | None
    current_prunable_lineage_record_count: int | None
    current_prunable_lineage_artifact_count: int | None
    latest_generated_at_utc: str | None
    latest_status: str | None
    latest_operator_id: str | None
    latest_trigger_mode: str | None
    latest_job_id: str | None
    latest_cleanup_mode: str | None
    latest_retention_days: int | None
    latest_age_seconds: float | None
    degradation_reasons: tuple[str, ...]
    degradation_details: tuple["RuntimeDegradationDetail", ...]


@dataclass(frozen=True)
class RuntimeRetentionPreviewFields:
    status: str
    reason: str | None
    cutoff_utc: str | None
    retention_days: int | None
    prunable_execution_count: int | None
    prunable_compute_job_count: int | None
    prunable_async_result_count: int | None
    prunable_lineage_record_count: int | None
    prunable_lineage_artifact_count: int | None


@dataclass(frozen=True)
class RuntimeRetentionDegradationPolicy:
    max_age_seconds: float
    active_run_age_seconds: float
    reclaim_count: int


@dataclass(frozen=True)
class OperatorActionStatus:
    status: str
    reason: str | None
    active_run_count: int
    oldest_active_run_operator_id: str | None
    oldest_active_run_tenant_id: str | None
    oldest_active_run_governed_target: str | None
    oldest_active_run_acquired_at_utc: str | None
    oldest_active_run_age_seconds: float | None
    latest_reclaimed_run_operator_id: str | None
    latest_reclaimed_run_tenant_id: str | None
    latest_reclaimed_run_governed_target: str | None
    latest_reclaimed_run_acquired_at_utc: str | None
    latest_reclaimed_run_reclaimed_at_utc: str | None
    latest_reclaimed_run_age_seconds: float | None
    reclaimed_run_count: int
    recent_reclaimed_runs: tuple["RecentOperatorActionReclaim", ...]


@dataclass(frozen=True)
class RecentOperatorActionReclaim:
    operator_id: str
    tenant_id: str | None
    governed_target: str
    acquired_at_utc: str
    reclaimed_at_utc: str
    reclaimed_age_seconds: float
    reclaim_count: int


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    generated_at: datetime
    runtime_status: str
    runtime_degradation_reasons: tuple[str, ...]
    runtime_degradation_details: tuple[RuntimeDegradationDetail, ...]
    draining: bool
    durable_metadata_store: DurabilityHealthStatus
    compute_queue: RuntimeQueueStatus
    lineage_queue: RuntimeQueueStatus
    recovery_drill: RecoveryDrillStatus
    runtime_retention: RuntimeRetentionStatus
    compute_queue_policy: ComputeQueueDegradationPolicy
    lineage_queue_policy: LineageQueueDegradationPolicy
    recovery_drill_policy: RecoveryDrillDegradationPolicy
    runtime_retention_policy: RuntimeRetentionDegradationPolicy
