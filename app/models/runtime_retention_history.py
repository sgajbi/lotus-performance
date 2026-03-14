from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.runtime_retention_history_service import RuntimeRetentionHistorySnapshot


class RuntimeRetentionHistoryEntryResponse(BaseModel):
    evidence_file_name: str = Field(description="Timestamped runtime-retention cleanup evidence artifact file name.")
    generated_at_utc: str = Field(description="UTC timestamp when this runtime-retention cleanup evidence was generated.")
    operator_id: str = Field(description="Operator or automation identity that ran the runtime-retention cleanup.")
    cleanup_mode: str = Field(description="Cleanup mode recorded for the retained runtime-retention execution.")
    status: str = Field(description="Outcome status recorded for the retained runtime-retention execution.")
    retention_days: int = Field(description="Retention window in days applied for this cleanup execution.")
    prunable_execution_count: int = Field(description="Terminal execution records selected by this cleanup execution.")
    prunable_compute_job_count: int = Field(description="Terminal compute jobs selected by this cleanup execution.")
    prunable_async_result_count: int = Field(description="Async results selected by this cleanup execution.")
    prunable_lineage_record_count: int = Field(description="Terminal lineage records selected by this cleanup execution.")
    prunable_lineage_artifact_count: int = Field(description="Lineage artifact directories selected by this cleanup execution.")


class RuntimeRetentionHistoryResponse(BaseModel):
    contract_version: str = Field(description="Version of the runtime-retention history response contract.")
    source_service: str = Field(description="Owning service that produced this runtime-retention history snapshot.")
    status: str = Field(description="Availability state of the retained runtime-retention history.")
    reason: str | None = Field(default=None, description="Concrete reason when retained runtime-retention history is unavailable.")
    artifact_directory: str = Field(description="Filesystem directory where retained runtime-retention evidence is stored.")
    latest_file_name: str | None = Field(default=None, description="Latest retained runtime-retention evidence artifact file name.")
    retained_file_names: list[str] = Field(default_factory=list, description="Retained timestamped runtime-retention evidence artifact file names.")
    retention_limit: int | None = Field(default=None, description="Configured retention limit for timestamped runtime-retention evidence artifacts.")
    retention_max_age_days: int | None = Field(default=None, description="Configured maximum age in days for retained runtime-retention evidence artifacts.")
    total_entries: int = Field(description="Total retained runtime-retention entries before any API-side filtering.")
    matched_entries: int = Field(description="Number of retained runtime-retention entries matching the applied filters before paging.")
    returned_entries: int = Field(description="Number of runtime-retention entries returned after applying filters.")
    next_offset: int | None = Field(default=None, description="Offset for the next page of retained runtime-retention entries when more filtered results remain.")
    applied_filters: dict[str, str | int] = Field(default_factory=dict, description="Query filters applied to the retained runtime-retention history response.")
    entries: list[RuntimeRetentionHistoryEntryResponse] = Field(default_factory=list, description="Retained runtime-retention history entries summarized from the manifest.")


def build_runtime_retention_history_response(snapshot: RuntimeRetentionHistorySnapshot) -> RuntimeRetentionHistoryResponse:
    return RuntimeRetentionHistoryResponse(
        contract_version="v1",
        source_service="lotus-performance",
        status=snapshot.status,
        reason=snapshot.reason,
        artifact_directory=snapshot.artifact_directory,
        latest_file_name=snapshot.latest_file_name,
        retained_file_names=list(snapshot.retained_file_names),
        retention_limit=snapshot.retention_limit,
        retention_max_age_days=snapshot.retention_max_age_days,
        total_entries=snapshot.total_entries,
        matched_entries=snapshot.matched_entries,
        returned_entries=snapshot.returned_entries,
        next_offset=snapshot.next_offset,
        applied_filters=snapshot.applied_filters,
        entries=[
            RuntimeRetentionHistoryEntryResponse(
                evidence_file_name=entry.evidence_file_name,
                generated_at_utc=entry.generated_at_utc,
                operator_id=entry.operator_id,
                cleanup_mode=entry.cleanup_mode,
                status=entry.status,
                retention_days=entry.retention_days,
                prunable_execution_count=entry.prunable_execution_count,
                prunable_compute_job_count=entry.prunable_compute_job_count,
                prunable_async_result_count=entry.prunable_async_result_count,
                prunable_lineage_record_count=entry.prunable_lineage_record_count,
                prunable_lineage_artifact_count=entry.prunable_lineage_artifact_count,
            )
            for entry in snapshot.entries
        ],
    )
