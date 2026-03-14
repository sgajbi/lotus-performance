from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.recovery_drill_history_service import RecoveryDrillHistorySnapshot


class RecoveryDrillHistoryEntryResponse(BaseModel):
    evidence_file_name: str = Field(description="Timestamped recovery-drill evidence artifact file name.")
    generated_at_utc: str = Field(description="UTC timestamp when this recovery drill evidence was generated.")
    operator_id: str = Field(description="Operator or automation identity that ran the recovery drill.")
    backup_identifier: str = Field(description="Backup or restore-set identifier validated by the recovery drill.")
    status: str = Field(description="Outcome status recorded for the retained recovery drill.")


class RecoveryDrillHistoryResponse(BaseModel):
    contract_version: str = Field(description="Version of the recovery-drill history response contract.")
    source_service: str = Field(description="Owning service that produced this recovery-drill history snapshot.")
    status: str = Field(description="Availability state of the retained recovery-drill history.")
    reason: str | None = Field(
        default=None,
        description="Concrete reason when retained recovery-drill history is unavailable.",
    )
    artifact_directory: str = Field(description="Filesystem directory where retained recovery-drill evidence is stored.")
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
    matched_entries: int = Field(description="Number of retained recovery-drill entries matching the applied filters before paging.")
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
                backup_identifier=entry.backup_identifier,
                status=entry.status,
            )
            for entry in snapshot.entries
        ],
    )
