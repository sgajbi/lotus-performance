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
