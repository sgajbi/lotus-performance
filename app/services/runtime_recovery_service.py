from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Protocol, TypedDict, TypeVar

from app.services.compute_job_store import ComputeRecoveryEvent, compute_job_store
from app.services.durability_health_service import (
    DurabilityHealthStatus,
    check_durable_metadata_schema_ready,
)
from app.services.lineage_metadata_store import LineageRecoveryEvent, lineage_metadata_store
from app.services.runtime_unavailability import durable_metadata_unavailable_reason

RecoveryEventT = TypeVar("RecoveryEventT")


class _RecoveryEventPage(Protocol[RecoveryEventT]):
    total_count: int
    next_offset: int | None
    next_cursor_recovered_before: str | None
    next_cursor_calculation_id_before: str | None
    items: list[RecoveryEventT]


class _RecoveryListCommonKwargs(TypedDict):
    limit: int
    offset: int
    recovered_after: datetime | None
    recovered_before: datetime | None
    cursor_recovered_before: datetime | None
    cursor_calculation_id_before: str | None
    calculation_id_contains: str | None


@dataclass(frozen=True)
class RuntimeRecoveryQueueState:
    status: str
    reason: str | None
    total_count: int
    returned_count: int
    next_offset: int | None
    next_cursor_recovered_before: str | None
    next_cursor_calculation_id_before: str | None


@dataclass(frozen=True)
class RuntimeRecoverySnapshot:
    generated_at: datetime
    queue_filter: str
    limit: int
    offset: int
    recovered_after: datetime | None
    recovered_before: datetime | None
    cursor_recovered_before: datetime | None
    cursor_calculation_id_before: str | None
    calculation_id_contains: str | None
    compute_analytics_type: str | None
    lineage_calculation_type: str | None
    durable_metadata_store: DurabilityHealthStatus
    compute_queue: RuntimeRecoveryQueueState
    lineage_queue: RuntimeRecoveryQueueState
    compute_recoveries: list[ComputeRecoveryEvent]
    lineage_recoveries: list[LineageRecoveryEvent]


@dataclass(frozen=True)
class _RuntimeRecoverySnapshotRequest:
    queue_filter: str
    limit: int
    offset: int
    recovered_after: datetime | None
    recovered_before: datetime | None
    cursor_recovered_before: datetime | None
    cursor_calculation_id_before: str | None
    calculation_id_contains: str | None
    compute_analytics_type: str | None
    lineage_calculation_type: str | None

    @property
    def include_compute(self) -> bool:
        return self.queue_filter in {"both", "compute"}

    @property
    def include_lineage(self) -> bool:
        return self.queue_filter in {"both", "lineage"}

    @property
    def recovery_filters(self) -> _RecoveryListFilters:
        return _RecoveryListFilters(
            limit=self.limit,
            offset=self.offset,
            recovered_after=self.recovered_after,
            recovered_before=self.recovered_before,
            cursor_recovered_before=self.cursor_recovered_before,
            cursor_calculation_id_before=self.cursor_calculation_id_before,
            calculation_id_contains=self.calculation_id_contains,
        )


def build_runtime_recovery_snapshot(
    *,
    queue_filter: str,
    limit: int,
    offset: int,
    recovered_after: datetime | None,
    recovered_before: datetime | None,
    cursor_recovered_before: datetime | None,
    cursor_calculation_id_before: str | None,
    calculation_id_contains: str | None,
    compute_analytics_type: str | None,
    lineage_calculation_type: str | None,
) -> RuntimeRecoverySnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_schema_ready()
    request = _RuntimeRecoverySnapshotRequest(
        queue_filter=queue_filter,
        limit=limit,
        offset=offset,
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        cursor_recovered_before=cursor_recovered_before,
        cursor_calculation_id_before=cursor_calculation_id_before,
        calculation_id_contains=calculation_id_contains,
        compute_analytics_type=compute_analytics_type,
        lineage_calculation_type=lineage_calculation_type,
    )

    if not durability_status.is_ready:
        return _unavailable_runtime_recovery_snapshot(
            generated_at=generated_at,
            request=request,
            durability_status=durability_status,
        )

    compute_queue, compute_recoveries = _safe_compute_recoveries(
        include_queue=request.include_compute,
        filters=request.recovery_filters,
        compute_analytics_type=request.compute_analytics_type,
    )
    lineage_queue, lineage_recoveries = _safe_lineage_recoveries(
        include_queue=request.include_lineage,
        filters=request.recovery_filters,
        lineage_calculation_type=request.lineage_calculation_type,
    )

    return _runtime_recovery_snapshot_from_request(
        generated_at=generated_at,
        request=request,
        durability_status=durability_status,
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        compute_recoveries=compute_recoveries,
        lineage_recoveries=lineage_recoveries,
    )


def _unavailable_runtime_recovery_snapshot(
    *,
    generated_at: datetime,
    request: _RuntimeRecoverySnapshotRequest,
    durability_status: DurabilityHealthStatus,
) -> RuntimeRecoverySnapshot:
    unavailable_queue = _queue_state(
        status="unavailable",
        reason=durable_metadata_unavailable_reason(durability_status),
    )
    return _runtime_recovery_snapshot_from_request(
        generated_at=generated_at,
        request=request,
        durability_status=durability_status,
        compute_queue=unavailable_queue,
        lineage_queue=unavailable_queue,
        compute_recoveries=[],
        lineage_recoveries=[],
    )


def _runtime_recovery_snapshot_from_request(
    *,
    generated_at: datetime,
    request: _RuntimeRecoverySnapshotRequest,
    durability_status: DurabilityHealthStatus,
    compute_queue: RuntimeRecoveryQueueState,
    lineage_queue: RuntimeRecoveryQueueState,
    compute_recoveries: list[ComputeRecoveryEvent],
    lineage_recoveries: list[LineageRecoveryEvent],
) -> RuntimeRecoverySnapshot:
    return RuntimeRecoverySnapshot(
        generated_at=generated_at,
        queue_filter=request.queue_filter,
        limit=request.limit,
        offset=request.offset,
        recovered_after=request.recovered_after,
        recovered_before=request.recovered_before,
        cursor_recovered_before=request.cursor_recovered_before,
        cursor_calculation_id_before=request.cursor_calculation_id_before,
        calculation_id_contains=request.calculation_id_contains,
        compute_analytics_type=request.compute_analytics_type,
        lineage_calculation_type=request.lineage_calculation_type,
        durable_metadata_store=durability_status,
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        compute_recoveries=compute_recoveries,
        lineage_recoveries=lineage_recoveries,
    )


def _safe_compute_recoveries(
    *,
    include_queue: bool,
    filters: _RecoveryListFilters,
    compute_analytics_type: str | None,
) -> tuple[RuntimeRecoveryQueueState, list[ComputeRecoveryEvent]]:
    return _safe_recoveries(
        include_queue=include_queue,
        filters=filters,
        load_page=lambda filters: compute_job_store.list_recent_recoveries(
            **filters.common_kwargs,
            analytics_type=compute_analytics_type,
        ),
    )


def _safe_lineage_recoveries(
    *,
    include_queue: bool,
    filters: _RecoveryListFilters,
    lineage_calculation_type: str | None,
) -> tuple[RuntimeRecoveryQueueState, list[LineageRecoveryEvent]]:
    return _safe_recoveries(
        include_queue=include_queue,
        filters=filters,
        load_page=lambda filters: lineage_metadata_store.list_recent_recoveries(
            **filters.common_kwargs,
            calculation_type=lineage_calculation_type,
        ),
    )


@dataclass(frozen=True)
class _RecoveryListFilters:
    limit: int
    offset: int
    recovered_after: datetime | None
    recovered_before: datetime | None
    cursor_recovered_before: datetime | None
    cursor_calculation_id_before: str | None
    calculation_id_contains: str | None

    @property
    def common_kwargs(self) -> _RecoveryListCommonKwargs:
        return {
            "limit": self.limit,
            "offset": self.offset,
            "recovered_after": self.recovered_after,
            "recovered_before": self.recovered_before,
            "cursor_recovered_before": self.cursor_recovered_before,
            "cursor_calculation_id_before": self.cursor_calculation_id_before,
            "calculation_id_contains": self.calculation_id_contains,
        }


def _safe_recoveries(
    *,
    include_queue: bool,
    filters: _RecoveryListFilters,
    load_page: Callable[[_RecoveryListFilters], _RecoveryEventPage[RecoveryEventT]],
) -> tuple[RuntimeRecoveryQueueState, list[RecoveryEventT]]:
    if not include_queue:
        return _queue_state(status="excluded"), []
    try:
        page = load_page(filters)
        return _queue_state_from_recovery_page(page), page.items
    except Exception as exc:
        return _queue_state(status="unavailable", reason=type(exc).__name__), []


def _queue_state_from_recovery_page(page: _RecoveryEventPage[RecoveryEventT]) -> RuntimeRecoveryQueueState:
    return _queue_state(
        status="available",
        total_count=page.total_count,
        returned_count=len(page.items),
        next_offset=page.next_offset,
        next_cursor_recovered_before=page.next_cursor_recovered_before,
        next_cursor_calculation_id_before=page.next_cursor_calculation_id_before,
    )


def _queue_state(
    *,
    status: str,
    reason: str | None = None,
    total_count: int = 0,
    returned_count: int = 0,
    next_offset: int | None = None,
    next_cursor_recovered_before: str | None = None,
    next_cursor_calculation_id_before: str | None = None,
) -> RuntimeRecoveryQueueState:
    return RuntimeRecoveryQueueState(
        status=status,
        reason=reason,
        total_count=total_count,
        returned_count=returned_count,
        next_offset=next_offset,
        next_cursor_recovered_before=next_cursor_recovered_before,
        next_cursor_calculation_id_before=next_cursor_calculation_id_before,
    )
