from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.compute_job_store import ComputeRecoveryEvent, ComputeRecoveryEventPage, compute_job_store
from app.services.durability_health_service import DurabilityHealthStatus, check_durable_metadata_store_ready
from app.services.lineage_metadata_store import LineageRecoveryEvent, LineageRecoveryEventPage, lineage_metadata_store


@dataclass(frozen=True)
class RuntimeRecoveryQueueState:
    status: str
    reason: str | None
    total_count: int
    returned_count: int


@dataclass(frozen=True)
class RuntimeRecoverySnapshot:
    generated_at: datetime
    queue_filter: str
    limit: int
    offset: int
    calculation_id_contains: str | None
    compute_analytics_type: str | None
    lineage_calculation_type: str | None
    durable_metadata_store: DurabilityHealthStatus
    compute_queue: RuntimeRecoveryQueueState
    lineage_queue: RuntimeRecoveryQueueState
    compute_recoveries: list[ComputeRecoveryEvent]
    lineage_recoveries: list[LineageRecoveryEvent]


def build_runtime_recovery_snapshot(
    *,
    queue_filter: str,
    limit: int,
    offset: int,
    calculation_id_contains: str | None,
    compute_analytics_type: str | None,
    lineage_calculation_type: str | None,
) -> RuntimeRecoverySnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_store_ready()

    if not durability_status.is_ready:
        unavailable_queue = RuntimeRecoveryQueueState(
            status="unavailable",
            reason=durability_status.reason or "durable_metadata_store_unreachable",
            total_count=0,
            returned_count=0,
        )
        return RuntimeRecoverySnapshot(
            generated_at=generated_at,
            queue_filter=queue_filter,
            limit=limit,
            offset=offset,
            calculation_id_contains=calculation_id_contains,
            compute_analytics_type=compute_analytics_type,
            lineage_calculation_type=lineage_calculation_type,
            durable_metadata_store=durability_status,
            compute_queue=unavailable_queue,
            lineage_queue=unavailable_queue,
            compute_recoveries=[],
            lineage_recoveries=[],
        )

    include_compute = queue_filter in {"both", "compute"}
    include_lineage = queue_filter in {"both", "lineage"}

    compute_queue, compute_recoveries = _safe_compute_recoveries(
        include_queue=include_compute,
        limit=limit,
        offset=offset,
        calculation_id_contains=calculation_id_contains,
        compute_analytics_type=compute_analytics_type,
    )
    lineage_queue, lineage_recoveries = _safe_lineage_recoveries(
        include_queue=include_lineage,
        limit=limit,
        offset=offset,
        calculation_id_contains=calculation_id_contains,
        lineage_calculation_type=lineage_calculation_type,
    )

    return RuntimeRecoverySnapshot(
        generated_at=generated_at,
        queue_filter=queue_filter,
        limit=limit,
        offset=offset,
        calculation_id_contains=calculation_id_contains,
        compute_analytics_type=compute_analytics_type,
        lineage_calculation_type=lineage_calculation_type,
        durable_metadata_store=durability_status,
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        compute_recoveries=compute_recoveries,
        lineage_recoveries=lineage_recoveries,
    )


def _safe_compute_recoveries(
    *,
    include_queue: bool,
    limit: int,
    offset: int,
    calculation_id_contains: str | None,
    compute_analytics_type: str | None,
) -> tuple[RuntimeRecoveryQueueState, list[ComputeRecoveryEvent]]:
    if not include_queue:
        return RuntimeRecoveryQueueState(status="excluded", reason=None, total_count=0, returned_count=0), []
    try:
        page: ComputeRecoveryEventPage = compute_job_store.list_recent_recoveries(
            limit=limit,
            offset=offset,
            analytics_type=compute_analytics_type,
            calculation_id_contains=calculation_id_contains,
        )
        return (
            RuntimeRecoveryQueueState(
                status="available",
                reason=None,
                total_count=page.total_count,
                returned_count=len(page.items),
            ),
            page.items,
        )
    except Exception as exc:
        return (
            RuntimeRecoveryQueueState(
                status="unavailable",
                reason=type(exc).__name__,
                total_count=0,
                returned_count=0,
            ),
            [],
        )


def _safe_lineage_recoveries(
    *,
    include_queue: bool,
    limit: int,
    offset: int,
    calculation_id_contains: str | None,
    lineage_calculation_type: str | None,
) -> tuple[RuntimeRecoveryQueueState, list[LineageRecoveryEvent]]:
    if not include_queue:
        return RuntimeRecoveryQueueState(status="excluded", reason=None, total_count=0, returned_count=0), []
    try:
        page: LineageRecoveryEventPage = lineage_metadata_store.list_recent_recoveries(
            limit=limit,
            offset=offset,
            calculation_type=lineage_calculation_type,
            calculation_id_contains=calculation_id_contains,
        )
        return (
            RuntimeRecoveryQueueState(
                status="available",
                reason=None,
                total_count=page.total_count,
                returned_count=len(page.items),
            ),
            page.items,
        )
    except Exception as exc:
        return (
            RuntimeRecoveryQueueState(
                status="unavailable",
                reason=type(exc).__name__,
                total_count=0,
                returned_count=0,
            ),
            [],
        )
