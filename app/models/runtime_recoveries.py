from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.runtime_status import DurableMetadataStoreStatusResponse
from app.services.calculation_id_filtering import (
    CALCULATION_ID_PREFIX_DESCRIPTION,
    CALCULATION_ID_PREFIX_MAX_LENGTH,
    CALCULATION_ID_PREFIX_MIN_LENGTH,
    CALCULATION_ID_PREFIX_PATTERN,
)
from app.services.compute_job_store import ComputeRecoveryEvent
from app.services.lineage_metadata_store import LineageRecoveryEvent
from app.services.operator_navigation_service import build_operator_navigation_links
from app.services.runtime_recovery_service import RuntimeRecoverySnapshot


class RuntimeRecoveriesQueryParams(BaseModel):
    queue: Literal["both", "compute", "lineage"] = Field(
        default="both",
        description="Queue scope for runtime recovery inspection.",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of recovery events to return per queue.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Zero-based page offset applied to each selected queue before limiting results.",
    )
    recovered_after: datetime | None = Field(
        default=None,
        description="Optional inclusive lower UTC timestamp bound applied to recovery-event timestamps.",
    )
    recovered_before: datetime | None = Field(
        default=None,
        description="Optional inclusive upper UTC timestamp bound applied to recovery-event timestamps.",
    )
    cursor_recovered_before: datetime | None = Field(
        default=None,
        description="Optional cursor recovery timestamp used for deterministic seek pagination of older matching events.",
    )
    cursor_calculation_id_before: str | None = Field(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Optional cursor calculation handle paired with the cursor recovery timestamp for seek pagination.",
    )
    compute_analytics_type: str | None = Field(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Optional compute analytics-type filter, such as ReturnsSeries or Attribution.",
    )
    lineage_calculation_type: str | None = Field(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Optional lineage calculation-type filter, such as TWR or Attribution.",
    )
    calculation_id_contains: str | None = Field(
        default=None,
        min_length=CALCULATION_ID_PREFIX_MIN_LENGTH,
        max_length=CALCULATION_ID_PREFIX_MAX_LENGTH,
        pattern=CALCULATION_ID_PREFIX_PATTERN,
        description=CALCULATION_ID_PREFIX_DESCRIPTION,
    )


class ComputeRecoveryEventResponse(BaseModel):
    calculation_id: str = Field(description="Calculation handle of the recovered compute job.")
    execution_path: str = Field(description="Execution polling path for the recovered compute job.")
    lineage_path: str = Field(description="Lineage inspection path for the recovered compute job.")
    result_path: str | None = Field(
        default=None,
        description="Async result path for the recovered compute job when the analytics family exposes a durable result route.",
    )
    analytics_type: str = Field(description="Analytics workflow type for the recovered compute job.")
    recovery_kind: str = Field(description="Recovery path that returned the compute job to pending state.")
    recovered_at_utc: str = Field(description="UTC timestamp when the compute job re-entered pending state.")
    attempt_count: int = Field(description="Attempt count already consumed by the recovered compute job.")
    error_type: str | None = Field(
        default=None,
        description="Last durable compute error type associated with the recovery event, when present.",
    )


class LineageRecoveryEventResponse(BaseModel):
    calculation_id: str = Field(description="Calculation handle of the recovered lineage item.")
    execution_path: str = Field(description="Execution polling path for the recovered lineage item.")
    lineage_path: str = Field(description="Lineage inspection path for the recovered lineage item.")
    result_path: str | None = Field(
        default=None,
        description="Async result path for the recovered lineage item when the calculation family exposes a durable result route.",
    )
    calculation_type: str = Field(description="Analytics workflow type for the recovered lineage item.")
    recovery_kind: str = Field(description="Recovery path that returned the lineage item to pending state.")
    recovered_at_utc: str = Field(description="UTC timestamp when the lineage item re-entered pending state.")
    attempt_count: int = Field(description="Attempt count already consumed by the recovered lineage item.")


class RuntimeRecoveriesQueueStatusResponse(BaseModel):
    status: str = Field(description="Availability of the queue-specific runtime recovery inspection surface.")
    reason: str | None = Field(
        default=None,
        description=(
            "Stable queue-specific unavailability reason when recovery inspection failed, such as "
            "compute_recovery_read_failed or lineage_recovery_read_failed."
        ),
    )
    total_count: int = Field(
        description="Total durable recovery events that match the requested filters for this queue."
    )
    returned_count: int = Field(
        description="Number of recovery events included for this queue in the current response page."
    )
    next_offset: int | None = Field(
        default=None,
        description="Next queue-local offset to request when additional matching recovery events remain.",
    )
    next_cursor_recovered_before: datetime | None = Field(
        default=None,
        description="Cursor recovery timestamp for deterministic seek pagination of older matching events.",
    )
    next_cursor_calculation_id_before: str | None = Field(
        default=None,
        description="Cursor calculation handle used with the cursor recovery timestamp to paginate older matching events.",
    )


class RuntimeRecoveriesResponse(BaseModel):
    contract_version: str = Field(description="Version of the runtime-recoveries response contract.")
    source_service: str = Field(description="Owning service that produced this runtime recovery snapshot.")
    generated_at: datetime = Field(description="Timestamp when the runtime recovery snapshot was generated.")
    queue_filter: str = Field(description="Requested queue filter applied to runtime recovery inspection.")
    limit: int = Field(description="Maximum number of recovery events returned per queue.")
    offset: int = Field(description="Zero-based page offset applied per queue before limiting results.")
    recovered_after: datetime | None = Field(
        default=None,
        description="Optional inclusive lower UTC timestamp bound applied to recovery-event timestamps.",
    )
    recovered_before: datetime | None = Field(
        default=None,
        description="Optional inclusive upper UTC timestamp bound applied to recovery-event timestamps.",
    )
    cursor_recovered_before: datetime | None = Field(
        default=None,
        description="Optional cursor recovery timestamp used for deterministic seek pagination of older matching events.",
    )
    cursor_calculation_id_before: str | None = Field(
        default=None,
        description="Optional cursor calculation handle paired with the cursor recovery timestamp for seek pagination.",
    )
    calculation_id_contains: str | None = Field(
        default=None,
        description=CALCULATION_ID_PREFIX_DESCRIPTION,
    )
    compute_analytics_type: str | None = Field(
        default=None,
        description="Optional compute analytics-type filter applied to compute recovery inspection.",
    )
    lineage_calculation_type: str | None = Field(
        default=None,
        description="Optional lineage calculation-type filter applied to lineage recovery inspection.",
    )
    durable_metadata_store: DurableMetadataStoreStatusResponse = Field(
        description="Availability of the durable metadata store backing runtime recovery inspection.",
    )
    compute_queue: RuntimeRecoveriesQueueStatusResponse = Field(
        description="Availability of compute recovery inspection for this snapshot.",
    )
    lineage_queue: RuntimeRecoveriesQueueStatusResponse = Field(
        description="Availability of lineage recovery inspection for this snapshot.",
    )
    compute_recoveries: list[ComputeRecoveryEventResponse] = Field(
        default_factory=list,
        description="Filtered compute recovery events ordered from most recent to least recent.",
    )
    lineage_recoveries: list[LineageRecoveryEventResponse] = Field(
        default_factory=list,
        description="Filtered lineage recovery events ordered from most recent to least recent.",
    )


def build_runtime_recoveries_response(snapshot: RuntimeRecoverySnapshot) -> RuntimeRecoveriesResponse:
    return RuntimeRecoveriesResponse(
        contract_version="v1",
        source_service="lotus-performance",
        generated_at=snapshot.generated_at,
        queue_filter=snapshot.queue_filter,
        limit=snapshot.limit,
        offset=snapshot.offset,
        recovered_after=snapshot.recovered_after,
        recovered_before=snapshot.recovered_before,
        cursor_recovered_before=snapshot.cursor_recovered_before,
        cursor_calculation_id_before=snapshot.cursor_calculation_id_before,
        calculation_id_contains=snapshot.calculation_id_contains,
        compute_analytics_type=snapshot.compute_analytics_type,
        lineage_calculation_type=snapshot.lineage_calculation_type,
        durable_metadata_store=DurableMetadataStoreStatusResponse(
            status=snapshot.durable_metadata_store.status,
            reason=snapshot.durable_metadata_store.reason,
        ),
        compute_queue=RuntimeRecoveriesQueueStatusResponse(
            status=snapshot.compute_queue.status,
            reason=snapshot.compute_queue.reason,
            total_count=snapshot.compute_queue.total_count,
            returned_count=snapshot.compute_queue.returned_count,
            next_offset=snapshot.compute_queue.next_offset,
            next_cursor_recovered_before=snapshot.compute_queue.next_cursor_recovered_before,
            next_cursor_calculation_id_before=snapshot.compute_queue.next_cursor_calculation_id_before,
        ),
        lineage_queue=RuntimeRecoveriesQueueStatusResponse(
            status=snapshot.lineage_queue.status,
            reason=snapshot.lineage_queue.reason,
            total_count=snapshot.lineage_queue.total_count,
            returned_count=snapshot.lineage_queue.returned_count,
            next_offset=snapshot.lineage_queue.next_offset,
            next_cursor_recovered_before=snapshot.lineage_queue.next_cursor_recovered_before,
            next_cursor_calculation_id_before=snapshot.lineage_queue.next_cursor_calculation_id_before,
        ),
        compute_recoveries=[
            ComputeRecoveryEventResponse(**_build_compute_recovery_payload(item))
            for item in snapshot.compute_recoveries
        ],
        lineage_recoveries=[
            LineageRecoveryEventResponse(**_build_lineage_recovery_payload(item))
            for item in snapshot.lineage_recoveries
        ],
    )


def _build_compute_recovery_payload(item: ComputeRecoveryEvent) -> dict[str, object]:
    links = build_operator_navigation_links(item.calculation_id, workflow_type=item.analytics_type)
    return {
        "calculation_id": item.calculation_id,
        "execution_path": links.execution_path,
        "lineage_path": links.lineage_path,
        "result_path": links.result_path,
        "analytics_type": item.analytics_type,
        "recovery_kind": item.recovery_kind,
        "recovered_at_utc": item.recovered_at_utc,
        "attempt_count": item.attempt_count,
        "error_type": item.error_type,
    }


def _build_lineage_recovery_payload(item: LineageRecoveryEvent) -> dict[str, object]:
    links = build_operator_navigation_links(item.calculation_id, workflow_type=item.calculation_type)
    return {
        "calculation_id": item.calculation_id,
        "execution_path": links.execution_path,
        "lineage_path": links.lineage_path,
        "result_path": links.result_path,
        "calculation_type": item.calculation_type,
        "recovery_kind": item.recovery_kind,
        "recovered_at_utc": item.recovered_at_utc,
        "attempt_count": item.attempt_count,
    }
