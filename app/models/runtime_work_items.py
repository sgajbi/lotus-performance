from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.runtime_status import DurableMetadataStoreStatusResponse
from app.services.compute_job_store import ComputeQueueInspectionItem
from app.services.lineage_metadata_store import LineageQueueInspectionItem
from app.services.operator_navigation_service import build_operator_navigation_links
from app.services.runtime_work_item_service import RuntimeWorkItemSnapshot


class ComputeRuntimeWorkItemResponse(BaseModel):
    calculation_id: str = Field(description="Calculation handle for the compute work item.")
    execution_path: str = Field(description="Execution polling path for this compute work item.")
    lineage_path: str = Field(description="Lineage inspection path for this compute work item.")
    result_path: str | None = Field(
        default=None,
        description="Async result path for this compute work item when the analytics family exposes a durable result route.",
    )
    analytics_type: str = Field(description="Analytics workflow type for the compute work item.")
    status: str = Field(description="Current compute work-item lifecycle state.")
    active_since_utc: str | None = Field(
        default=None,
        description="UTC timestamp when this work item entered its current active or terminal state.",
    )
    age_seconds: float | None = Field(
        default=None,
        description="Age in seconds since the compute work item entered its current active or terminal state.",
    )
    attempt_count: int = Field(description="Number of execution attempts already consumed by this compute job.")
    max_attempts: int = Field(description="Configured maximum execution attempts for this compute job.")
    error_type: str | None = Field(
        default=None,
        description="Last durable compute failure type for this work item, when present.",
    )
    error_message: str | None = Field(
        default=None,
        description="Last durable compute failure message for this work item, when present.",
    )


class LineageRuntimeWorkItemResponse(BaseModel):
    calculation_id: str = Field(description="Calculation handle for the lineage work item.")
    execution_path: str = Field(description="Execution polling path for this lineage work item.")
    lineage_path: str = Field(description="Lineage inspection path for this lineage work item.")
    result_path: str | None = Field(
        default=None,
        description="Async result path for this lineage work item when the calculation family exposes a durable result route.",
    )
    calculation_type: str = Field(description="Analytics workflow type that produced this lineage work item.")
    status: str = Field(description="Current lineage work-item lifecycle state.")
    active_since_utc: str | None = Field(
        default=None,
        description="UTC timestamp when this lineage item entered its current active or terminal state.",
    )
    age_seconds: float | None = Field(
        default=None,
        description="Age in seconds since the lineage item entered its current active or terminal state.",
    )
    attempt_count: int = Field(description="Number of materialization attempts already consumed by this lineage item.")
    error_message: str | None = Field(
        default=None,
        description="Last durable lineage failure message for this work item, when present.",
    )


class RuntimeWorkItemQueueStatusResponse(BaseModel):
    status: str = Field(description="Availability of the queue-specific work-item inspection surface.")
    reason: str | None = Field(
        default=None,
        description="Concrete queue-specific unavailability reason when work-item inspection failed.",
    )
    total_count: int = Field(description="Total durable work items that match the requested filters for this queue.")
    returned_count: int = Field(
        description="Number of work items included for this queue in the current response page."
    )
    next_offset: int | None = Field(
        default=None,
        description="Next queue-local offset to request when additional matching work items remain.",
    )


class RuntimeWorkItemsResponse(BaseModel):
    contract_version: str = Field(description="Version of the runtime-work-items response contract.")
    source_service: str = Field(description="Owning service that produced this runtime work-item snapshot.")
    generated_at: datetime = Field(description="Timestamp when the runtime work-item snapshot was generated.")
    queue_filter: str = Field(description="Requested queue filter applied to runtime work-item inspection.")
    status_filter: str = Field(description="Requested work-item status filter applied to both queues.")
    limit: int = Field(description="Maximum number of work items returned per queue.")
    offset: int = Field(description="Zero-based page offset applied per queue before limiting results.")
    min_age_seconds: float = Field(
        description="Minimum work-item age filter applied after durable ordering for this snapshot."
    )
    compute_analytics_type: str | None = Field(
        default=None,
        description="Optional compute analytics-type filter applied to compute work-item inspection.",
    )
    lineage_calculation_type: str | None = Field(
        default=None,
        description="Optional lineage calculation-type filter applied to lineage work-item inspection.",
    )
    calculation_id_contains: str | None = Field(
        default=None,
        description="Optional substring filter applied to calculation identifiers in both selected queues.",
    )
    durable_metadata_store: DurableMetadataStoreStatusResponse = Field(
        description="Availability of the durable metadata store backing compute and lineage work items.",
    )
    compute_queue: RuntimeWorkItemQueueStatusResponse = Field(
        description="Availability of compute work-item inspection for this snapshot.",
    )
    lineage_queue: RuntimeWorkItemQueueStatusResponse = Field(
        description="Availability of lineage work-item inspection for this snapshot.",
    )
    compute_items: list[ComputeRuntimeWorkItemResponse] = Field(
        default_factory=list,
        description="Filtered compute work items ordered for operator drill-down.",
    )
    lineage_items: list[LineageRuntimeWorkItemResponse] = Field(
        default_factory=list,
        description="Filtered lineage work items ordered for operator drill-down.",
    )


def build_runtime_work_items_response(snapshot: RuntimeWorkItemSnapshot) -> RuntimeWorkItemsResponse:
    return RuntimeWorkItemsResponse(
        contract_version="v1",
        source_service="lotus-performance",
        generated_at=snapshot.generated_at,
        queue_filter=snapshot.queue_filter,
        status_filter=snapshot.status_filter,
        limit=snapshot.limit,
        offset=snapshot.offset,
        min_age_seconds=snapshot.min_age_seconds,
        compute_analytics_type=snapshot.compute_analytics_type,
        lineage_calculation_type=snapshot.lineage_calculation_type,
        calculation_id_contains=snapshot.calculation_id_contains,
        durable_metadata_store=DurableMetadataStoreStatusResponse(
            status=snapshot.durable_metadata_store.status,
            reason=snapshot.durable_metadata_store.reason,
        ),
        compute_queue=RuntimeWorkItemQueueStatusResponse(
            status=snapshot.compute_queue.status,
            reason=snapshot.compute_queue.reason,
            total_count=snapshot.compute_queue.total_count,
            returned_count=snapshot.compute_queue.returned_count,
            next_offset=snapshot.compute_queue.next_offset,
        ),
        lineage_queue=RuntimeWorkItemQueueStatusResponse(
            status=snapshot.lineage_queue.status,
            reason=snapshot.lineage_queue.reason,
            total_count=snapshot.lineage_queue.total_count,
            returned_count=snapshot.lineage_queue.returned_count,
            next_offset=snapshot.lineage_queue.next_offset,
        ),
        compute_items=[
            ComputeRuntimeWorkItemResponse(**_build_compute_item_payload(item)) for item in snapshot.compute_items
        ],
        lineage_items=[
            LineageRuntimeWorkItemResponse(**_build_lineage_item_payload(item)) for item in snapshot.lineage_items
        ],
    )


def _build_compute_item_payload(item: ComputeQueueInspectionItem) -> dict[str, object]:
    links = build_operator_navigation_links(item.calculation_id, workflow_type=item.analytics_type)
    return {
        "calculation_id": item.calculation_id,
        "execution_path": links.execution_path,
        "lineage_path": links.lineage_path,
        "result_path": links.result_path,
        "analytics_type": item.analytics_type,
        "status": item.status,
        "active_since_utc": item.active_since_utc,
        "age_seconds": item.age_seconds,
        "attempt_count": item.attempt_count,
        "max_attempts": item.max_attempts,
        "error_type": item.error_type,
        "error_message": item.error_message,
    }


def _build_lineage_item_payload(item: LineageQueueInspectionItem) -> dict[str, object]:
    links = build_operator_navigation_links(item.calculation_id, workflow_type=item.calculation_type)
    return {
        "calculation_id": item.calculation_id,
        "execution_path": links.execution_path,
        "lineage_path": links.lineage_path,
        "result_path": links.result_path,
        "calculation_type": item.calculation_type,
        "status": item.status,
        "active_since_utc": item.active_since_utc,
        "age_seconds": item.age_seconds,
        "attempt_count": item.attempt_count,
        "error_message": item.error_message,
    }
