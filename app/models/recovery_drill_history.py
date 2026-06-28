from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.operator_run_response import build_lotus_performance_operator_run_response
from app.services.recovery_drill_history_service import RecoveryDrillHistorySnapshot


class RecoveryDrillHistoryQueryParams(BaseModel):
    limit: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum number of retained recovery-drill entries to return.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Zero-based offset into the filtered retained recovery-drill history.",
    )
    operator_id: str | None = Field(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Operator or automation identity filter.",
    )
    backup_identifier: str | None = Field(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Backup or restore-set identifier filter.",
    )
    status: str | None = Field(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Recovery-drill outcome status filter.",
    )
    generated_after: str | None = Field(
        default=None,
        description="Filter to entries generated at or after this UTC timestamp.",
    )
    generated_before: str | None = Field(
        default=None,
        description="Filter to entries generated at or before this UTC timestamp.",
    )


class RecoveryDrillHistoryEntryResponse(BaseModel):
    evidence_file_name: str = Field(description="Timestamped recovery-drill evidence artifact file name.")
    generated_at_utc: str = Field(description="UTC timestamp when this recovery drill evidence was generated.")
    operator_id: str = Field(description="Operator or automation identity that ran the recovery drill.")
    tenant_id: str | None = Field(
        default=None, description="Enterprise tenant identity retained with this recovery drill, when present."
    )
    correlation_id: str | None = Field(
        default=None, description="Enterprise correlation identifier retained with this recovery drill, when present."
    )
    backup_identifier: str = Field(description="Backup or restore-set identifier validated by the recovery drill.")
    status: str = Field(description="Outcome status recorded for the retained recovery drill.")


class RecoveryDrillRunRequest(BaseModel):
    backup_identifier: str = Field(
        min_length=1,
        pattern=r".*\S.*",
        description="Backup or restore-set identifier to validate with this recovery drill.",
    )

    @field_validator("backup_identifier")
    @classmethod
    def normalize_backup_identifier(cls, value: str) -> str:
        return value.strip()


class RecoveryDrillRunResponse(BaseModel):
    contract_version: str = Field(description="Version of the recovery-drill run response contract.")
    source_service: str = Field(description="Owning service that executed the recovery-drill run request.")
    drill_name: str = Field(description="Logical name of the durable recovery drill action.")
    generated_at_utc: str = Field(description="UTC timestamp when this recovery drill evidence was generated.")
    evidence_file_name: str = Field(description="Timestamped recovery-drill evidence artifact file name.")
    operator_id: str = Field(description="Enterprise actor or service identity recorded for this recovery drill run.")
    tenant_id: str | None = Field(
        default=None, description="Enterprise tenant identity recorded for this recovery drill run, when present."
    )
    correlation_id: str | None = Field(
        default=None,
        description="Enterprise correlation identifier recorded for this recovery drill run, when present.",
    )
    backup_identifier: str = Field(description="Backup or restore-set identifier validated by this recovery drill.")
    status: str = Field(description="Outcome status recorded for this recovery drill run.")
    database_path: str = Field(description="Ephemeral durable metadata database path used during the recovery drill.")
    restored_schema_mode: str = Field(description="Schema restore or upgrade mode exercised during the recovery drill.")
    owned_tables_present: list[str] = Field(
        description="Owned durable tables confirmed present during the recovery drill."
    )
    compute_job_processed_count: int = Field(description="Compute jobs processed during the recovery drill.")
    compute_async_result_status: str = Field(description="Async result status observed during the recovery drill.")
    compute_execution_status: str = Field(description="Execution status observed during the recovery drill.")
    processed_payload_count: int = Field(description="Lineage payloads processed during the recovery drill.")
    materialized_artifact_path: str = Field(description="Materialized artifact path produced by the recovery drill.")
    materialized_artifact_exists: bool = Field(
        description="Whether the recovery drill confirmed the expected lineage artifact exists."
    )


class RecoveryDrillHistoryResponse(BaseModel):
    contract_version: str = Field(description="Version of the recovery-drill history response contract.")
    source_service: str = Field(description="Owning service that produced this recovery-drill history snapshot.")
    status: str = Field(description="Availability state of the retained recovery-drill history.")
    reason: str | None = Field(
        default=None,
        description="Concrete reason when retained recovery-drill history is unavailable.",
    )
    artifact_directory: str = Field(
        description="Filesystem directory where retained recovery-drill evidence is stored."
    )
    latest_file_name: str | None = Field(
        default=None,
        description="Latest retained recovery-drill evidence artifact file name.",
    )
    retained_file_names: list[str] = Field(
        default_factory=list,
        description="Retained timestamped recovery-drill evidence artifact file names.",
    )
    retention_limit: int | None = Field(
        default=None,
        description="Configured retention limit for timestamped recovery-drill evidence artifacts.",
    )
    retention_max_age_days: int | None = Field(
        default=None,
        description="Configured maximum age in days for retained recovery-drill evidence artifacts.",
    )
    total_entries: int = Field(description="Total retained recovery-drill entries before any API-side filtering.")
    matched_entries: int = Field(
        description="Number of retained recovery-drill entries matching the applied filters before paging."
    )
    returned_entries: int = Field(description="Number of recovery-drill entries returned after applying filters.")
    next_offset: int | None = Field(
        default=None,
        description="Offset for the next page of retained recovery-drill entries when more filtered results remain.",
    )
    applied_filters: dict[str, str | int] = Field(
        default_factory=dict,
        description="Query filters applied to the retained recovery-drill history response.",
    )
    entries: list[RecoveryDrillHistoryEntryResponse] = Field(
        default_factory=list,
        description="Retained recovery-drill history entries summarized from the manifest.",
    )


def build_recovery_drill_history_response(snapshot: RecoveryDrillHistorySnapshot) -> RecoveryDrillHistoryResponse:
    return RecoveryDrillHistoryResponse(
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
            RecoveryDrillHistoryEntryResponse(
                evidence_file_name=entry.evidence_file_name,
                generated_at_utc=entry.generated_at_utc,
                operator_id=entry.operator_id,
                tenant_id=entry.tenant_id,
                correlation_id=entry.correlation_id,
                backup_identifier=entry.backup_identifier,
                status=entry.status,
            )
            for entry in snapshot.entries
        ],
    )


def build_recovery_drill_run_response(
    *,
    drill_name: str,
    generated_at_utc: str,
    evidence_file_name: str,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str | None,
    backup_identifier: str,
    status: str,
    database_path: str,
    restored_schema_mode: str,
    owned_tables_present: list[str],
    compute_job_processed_count: int,
    compute_async_result_status: str,
    compute_execution_status: str,
    processed_payload_count: int,
    materialized_artifact_path: str,
    materialized_artifact_exists: bool,
) -> RecoveryDrillRunResponse:
    return build_lotus_performance_operator_run_response(
        RecoveryDrillRunResponse,
        **locals(),
    )
