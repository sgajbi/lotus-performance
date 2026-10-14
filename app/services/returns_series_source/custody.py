"""Portfolio source-root selection inside the execution owner's transaction."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import inspect, select, update
from sqlalchemy.orm import Session

from app.services.lineage_metadata_store import (
    LineagePayloadLeaseOwnershipError,
    LineagePayloadModel,
    LineageRecordModel,
    LineageStatus,
)


class SourceCustodyConflict(ValueError):
    """The retained identity or current execution authority does not permit this write."""


@dataclass(frozen=True)
class SourceCustodyClaim:
    calculation_id: UUID
    tenant_id: str
    attempt_id: str
    attempt_number: int

    def validate(self) -> None:
        if (
            not self.tenant_id
            or self.tenant_id != self.tenant_id.strip()
            or not self.attempt_id
            or self.attempt_id != self.attempt_id.strip()
            or type(self.attempt_number) is not int
            or self.attempt_number < 0
        ):
            raise SourceCustodyConflict("Explicit source tenant and attempt required.")


@dataclass(frozen=True)
class SourceCustodySelection:
    tenant_id: str
    attempt_id: str
    attempt_number: int
    state: str
    root_digest: str | None
    manifest_digest: str | None


@dataclass(frozen=True)
class SourceMaterializationPayload:
    request_json: str
    response_json: str


def select_source_root(
    session: Session,
    *,
    claim: SourceCustodyClaim,
    root_digest: str | None,
    failure: str | None = None,
    materialization: SourceMaterializationPayload | None = None,
) -> SourceCustodySelection:
    """Called only after the owning store locks and validates its execution claim.

    A new attempt may replace an unfinished capture, but can never replace a
    frozen root. The original attempt remains the identity of frozen files.
    """
    claim.validate()
    if root_digest is not None and re.fullmatch(r"[0-9a-f]{64}", root_digest) is None:
        raise SourceCustodyConflict("Invalid source root digest.")
    row = _source_record(session, claim)
    _require_source_record_scope(row, claim)
    if row.status == LineageStatus.FAILED.value:
        if (root_digest, failure, materialization) != (None, None, None):
            raise SourceCustodyConflict("Terminal source failure cannot be reset.")
        return _selection(row)
    _apply_root_selection(
        row,
        claim=claim,
        root_digest=root_digest,
        beginning_capture=(root_digest, failure, materialization) == (None, None, None),
    )
    if failure is not None:
        _fail_source_capture(row, failure)
    if materialization is not None:
        _enqueue_selected_source(session, row=row, payload=materialization)
    session.flush()
    return _selection(row)


def require_existing_frozen_source(session: Session, *, claim: SourceCustodyClaim) -> SourceCustodySelection:
    """Read only: the caller has already locked execution and the current compute owner."""
    row = session.execute(
        select(LineageRecordModel)
        .where(LineageRecordModel.calculation_id == str(claim.calculation_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise SourceCustodyConflict("Completed publication requires existing frozen custody.")
    _require_source_record_scope(row, claim)
    expected_status = {
        "frozen": LineageStatus.PENDING.value,
        "pending_materialization": LineageStatus.PENDING.value,
        "complete": LineageStatus.COMPLETE.value,
    }.get(row.source_custody_state)
    if expected_status is None or row.status != expected_status:
        raise SourceCustodyConflict("Completed publication requires immutable frozen custody.")
    _require_frozen_source_identity(row)
    return _selection(row)


def _require_frozen_source_identity(row: LineageRecordModel) -> None:
    if (
        re.fullmatch(r"[0-9a-f]{64}", row.source_root_digest or "") is None
        or not row.source_attempt_id
        or row.source_attempt_number is None
        or row.source_attempt_number < 0
    ):
        raise SourceCustodyConflict("Completed publication requires immutable frozen identity.")


def require_immutable_source_response(session: Session, *, claim: SourceCustodyClaim, response: dict[str, Any]) -> None:
    """Bind the cached envelope to the immutable queued or materialized original."""
    payload = session.get(LineagePayloadModel, str(claim.calculation_id))
    if payload is not None:
        if json.loads(payload.response_json) != response:
            raise SourceCustodyConflict("Completed publication differs from its immutable source response.")
        return
    row = session.get(LineageRecordModel, str(claim.calculation_id))
    if row is None or row.source_custody_state != "complete":
        raise SourceCustodyConflict("Immutable completed publication response authority is unavailable.")
    from app.models.returns_series import ReturnsSeriesResponse

    try:
        original = ReturnsSeriesResponse.model_validate(response)
    except ValueError:
        raise SourceCustodyConflict("Completed publication response is invalid.") from None
    digest = hashlib.sha256(original.model_dump_json().encode()).hexdigest()
    if (
        original.model_dump(mode="json") != response
        or f"source-{digest}.response.json" not in row.artifact_names.splitlines()
    ):
        raise SourceCustodyConflict("Completed publication differs from its selected immutable response digest.")


def _apply_root_selection(
    row: LineageRecordModel, *, claim: SourceCustodyClaim, root_digest: str | None, beginning_capture: bool
) -> None:
    if row.source_root_digest is not None:
        if root_digest is not None and row.source_root_digest != root_digest:
            raise SourceCustodyConflict("An immutable source root is already selected.")
    else:
        _select_unfrozen_root(row, claim=claim, root_digest=root_digest, beginning_capture=beginning_capture)


def _source_record(session: Session, claim: SourceCustodyClaim) -> LineageRecordModel:
    row = session.execute(
        select(LineageRecordModel)
        .where(LineageRecordModel.calculation_id == str(claim.calculation_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = LineageRecordModel(
            calculation_id=str(claim.calculation_id),
            calculation_type="ReturnsSeries",
            status=LineageStatus.PENDING.value,
            timestamp_utc=datetime.now(timezone.utc),
            artifact_names="",
            source_tenant_id=claim.tenant_id,
            source_attempt_id=claim.attempt_id,
            source_attempt_number=claim.attempt_number,
            source_custody_state="capturing",
        )
        session.add(row)
    return row


def _require_source_record_scope(row: LineageRecordModel, claim: SourceCustodyClaim) -> None:
    if row.calculation_type != "ReturnsSeries" or row.source_tenant_id != claim.tenant_id:
        raise SourceCustodyConflict("Source custody tenant or workflow conflict.")
    if claim.attempt_number == 0 and (row.source_attempt_id, row.source_attempt_number) != (claim.attempt_id, 0):
        raise SourceCustodyConflict("Source custody belongs to a different inline attempt.")


def _select_unfrozen_root(
    row: LineageRecordModel, *, claim: SourceCustodyClaim, root_digest: str | None, beginning_capture: bool
) -> None:
    if row.status != LineageStatus.PENDING.value:
        raise SourceCustodyConflict("Terminal lineage cannot select a source root.")
    different_attempt = (row.source_attempt_id, row.source_attempt_number) != (claim.attempt_id, claim.attempt_number)
    if different_attempt and (not beginning_capture or claim.attempt_number <= (row.source_attempt_number or 0)):
        raise SourceCustodyConflict("Source capture attempt was superseded.")
    row.source_attempt_id = claim.attempt_id
    row.source_attempt_number = claim.attempt_number
    row.source_custody_state = "capturing" if root_digest is None else "frozen"
    row.source_root_digest = root_digest


def _fail_source_capture(row: LineageRecordModel, failure: str) -> None:
    if row.status == LineageStatus.COMPLETE.value:
        raise SourceCustodyConflict("Completed source custody cannot be reset.")
    row.source_custody_state = "failed"
    row.status = LineageStatus.FAILED.value
    row.error_message = failure


def _selection(row: LineageRecordModel) -> SourceCustodySelection:
    return SourceCustodySelection(
        tenant_id=row.source_tenant_id or "",
        attempt_id=row.source_attempt_id or "",
        attempt_number=row.source_attempt_number or 0,
        state=row.source_custody_state or "",
        root_digest=row.source_root_digest,
        manifest_digest=row.source_manifest_digest,
    )


def _enqueue_selected_source(
    session: Session, *, row: LineageRecordModel, payload: SourceMaterializationPayload
) -> None:
    if row.source_root_digest is None or row.source_custody_state not in {
        "frozen",
        "pending_materialization",
        "complete",
    }:
        raise SourceCustodyConflict("Only verified frozen source evidence may be enqueued.")
    existing = session.get(LineagePayloadModel, row.calculation_id)
    if existing is not None:
        if existing.request_json != payload.request_json or existing.response_json != payload.response_json:
            raise SourceCustodyConflict("Source materialization payload is immutable.")
        return
    if row.source_custody_state == "complete":
        return
    if row.status != LineageStatus.PENDING.value:
        raise SourceCustodyConflict("Terminal lineage cannot be reset by enqueue.")
    session.add(
        LineagePayloadModel(
            calculation_id=row.calculation_id,
            calculation_type=row.calculation_type,
            request_json=payload.request_json,
            response_json=payload.response_json,
            details_json="{}",
            created_at_utc=datetime.now(timezone.utc),
            attempt_count=0,
        )
    )
    row.source_custody_state = "pending_materialization"


def source_completion_values(
    session: Session,
    *,
    record: LineageRecordModel,
    payload: LineagePayloadModel | None,
    root_digest: str | None,
    manifest_digest: str | None,
    tenant_id: str | None,
    worker_id: str | None,
    attempt_count: int | None,
) -> dict[str, object]:
    if record.source_custody_state is None:
        return {}
    _require_source_completion_attempt(payload, worker_id, attempt_count)
    _require_source_completion_root(record, root_digest, manifest_digest, tenant_id)
    _require_source_completion_execution(session, record.calculation_id, tenant_id)
    return {"source_custody_state": "complete", "source_manifest_digest": manifest_digest}


def _require_source_completion_attempt(
    payload: LineagePayloadModel | None, worker_id: str | None, attempt_count: int | None
) -> None:
    if (
        worker_id is None
        or payload is None
        or payload.worker_id != worker_id
        or attempt_count is None
        or payload.attempt_count != attempt_count
    ):
        raise LineagePayloadLeaseOwnershipError("Source completion requires the current lineage attempt.")


def _require_source_completion_root(
    record: LineageRecordModel, root: str | None, manifest: str | None, tenant: str | None
) -> None:
    if root is None or manifest is None or tenant is None:
        raise LineagePayloadLeaseOwnershipError("Source completion identity is unavailable.")
    if re.fullmatch(r"[0-9a-f]{64}", manifest) is None:
        raise LineagePayloadLeaseOwnershipError("Source completion manifest digest is invalid.")
    if (
        record.source_root_digest != root
        or record.source_tenant_id != tenant
        or record.source_custody_state != "pending_materialization"
    ):
        raise LineagePayloadLeaseOwnershipError("Source completion root or tenant differs from retained authority.")


def _require_source_completion_execution(session: Session, calculation_id: str, tenant_id: str | None) -> None:
    from app.services.execution_registry import AnalyticsExecutionModel, ExecutionStatus

    execution = session.get(AnalyticsExecutionModel, calculation_id)
    if (
        execution is None
        or execution.tenant_id != tenant_id
        or execution.analytics_type != "ReturnsSeries"
        or execution.status == ExecutionStatus.FAILED.value
    ):
        raise LineagePayloadLeaseOwnershipError("Source completion requires retained execution authority.")


def require_source_retry_record(session: Session, record: LineageRecordModel | None) -> None:
    if (
        record is None
        or record.status != LineageStatus.PENDING.value
        or record.source_custody_state != "pending_materialization"
        or record.source_root_digest is None
        or record.source_tenant_id is None
    ):
        raise LineagePayloadLeaseOwnershipError("Source retry requires pending retained authority.")
    _require_source_completion_execution(session, record.calculation_id, record.source_tenant_id)


def fail_terminal_source_custody(
    session: Session | None, *, calculation_ids: list[str], tenant_id: str | None, analytics_type: str | None
) -> None:
    """Called within the owning terminal transition, never by a detached worker.

    Historical store-only schemas contain no source custody. Runtime admission
    separately requires the complete schema before any source capture is enabled.
    """
    if session is None or tenant_id is None or analytics_type != "ReturnsSeries":
        return
    if not inspect(session.connection()).has_table("lineage_records"):
        return
    session.execute(
        update(LineageRecordModel)
        .where(
            LineageRecordModel.calculation_id.in_(calculation_ids),
            LineageRecordModel.calculation_type == "ReturnsSeries",
            LineageRecordModel.source_tenant_id == tenant_id,
            LineageRecordModel.source_custody_state.in_(["capturing", "frozen", "pending_materialization"]),
        )
        .values(
            status=LineageStatus.FAILED.value,
            source_custody_state="failed",
            error_message="Arithmetic execution terminated before complete source custody.",
            timestamp_utc=datetime.now(timezone.utc),
        )
    )
