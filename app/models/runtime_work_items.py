from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.runtime_status import DurableMetadataStoreStatusResponse
from app.services.runtime_work_item_service import RuntimeWorkItemSnapshot


class ComputeRuntimeWorkItemResponse(BaseModel):
    calculation_id: str = Field(description="Calculation handle for the compute work item.")
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


class RuntimeWorkItemsResponse(BaseModel):
    contract_version: str = Field(description="Version of the runtime-work-items response contract.")
    source_service: str = Field(description="Owning service that produced this runtime work-item snapshot.")
    generated_at: datetime = Field(description="Timestamp when the runtime work-item snapshot was generated.")
    status_filter: str = Field(description="Requested work-item status filter applied to both queues.")
    limit: int = Field(description="Maximum number of work items returned per queue.")
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
        status_filter=snapshot.status_filter,
        limit=snapshot.limit,
        durable_metadata_store=DurableMetadataStoreStatusResponse(
            status=snapshot.durable_metadata_store.status,
            reason=snapshot.durable_metadata_store.reason,
        ),
        compute_queue=RuntimeWorkItemQueueStatusResponse(
            status=snapshot.compute_queue.status,
            reason=snapshot.compute_queue.reason,
        ),
        lineage_queue=RuntimeWorkItemQueueStatusResponse(
            status=snapshot.lineage_queue.status,
            reason=snapshot.lineage_queue.reason,
        ),
        compute_items=[
            ComputeRuntimeWorkItemResponse(
                calculation_id=item.calculation_id,
                analytics_type=item.analytics_type,
                status=item.status,
                active_since_utc=item.active_since_utc,
                age_seconds=item.age_seconds,
                attempt_count=item.attempt_count,
                max_attempts=item.max_attempts,
                error_type=item.error_type,
                error_message=item.error_message,
            )
            for item in snapshot.compute_items
        ],
        lineage_items=[
            LineageRuntimeWorkItemResponse(
                calculation_id=item.calculation_id,
                calculation_type=item.calculation_type,
                status=item.status,
                active_since_utc=item.active_since_utc,
                age_seconds=item.age_seconds,
                attempt_count=item.attempt_count,
                error_message=item.error_message,
            )
            for item in snapshot.lineage_items
        ],
    )
