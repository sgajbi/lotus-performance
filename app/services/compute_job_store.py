from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterable, Iterator, cast
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text, case, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings
from app.services.calculation_id_filtering import apply_calculation_id_prefix_filter
from app.services.durable_database_engine import create_durable_database_engine
from app.services.durable_store_inspection import (
    INSPECTION_STATUS_ACTIVE,
    INSPECTION_STATUS_ALL,
    INSPECTION_STATUS_FAILED,
    INSPECTION_STATUS_RECLAIMABLE,
    InspectionQueryContext,
    apply_min_age_filter,
    build_inspection_query_context,
)
from app.services.durable_store_json import load_json_object_or_none
from app.services.durable_store_pagination import next_offset_or_none, recovery_cursor_or_none
from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store
from app.services.durable_store_time import (
    elapsed_seconds_since,
    elapsed_seconds_since_or_zero,
    format_timestamp,
    normalize_filter_datetime,
)

logger = logging.getLogger(__name__)

INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_ERROR_TYPE = "InvalidComputeJobRequestPayload"
INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_MESSAGE = "Stored compute job request payload is invalid."
INVALID_COMPUTE_JOB_RESPONSE_PAYLOAD_ERROR_TYPE = "InvalidComputeJobResponsePayload"
INVALID_COMPUTE_JOB_RESPONSE_PAYLOAD_MESSAGE = "Stored compute job response payload is invalid."


class ComputeJobLeaseOwnershipError(ValueError):
    """Raised when a worker tries to finalize a job it no longer owns."""


class ComputeJobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ComputeJobRegistrationStatus(StrEnum):
    CREATED = "created"
    REPLAY = "replay"
    CONFLICT = "conflict"


COMPUTE_ACTIVE_INSPECTION_STATUSES = (
    ComputeJobStatus.PENDING.value,
    ComputeJobStatus.LEASED.value,
    ComputeJobStatus.RUNNING.value,
)
COMPUTE_RECLAIMABLE_INSPECTION_STATUSES = (
    ComputeJobStatus.LEASED.value,
    ComputeJobStatus.RUNNING.value,
)
COMPUTE_TERMINAL_JOB_STATUSES = (
    ComputeJobStatus.COMPLETE.value,
    ComputeJobStatus.FAILED.value,
)
TRANSIENT_COMPUTE_JOB_REQUEST_FIELDS = frozenset({"observability_context"})
COMPUTE_INSPECTION_ACTIVE_SINCE_FIELDS: dict[str, tuple[str, ...]] = {
    ComputeJobStatus.LEASED.value: ("leased_at_utc", "created_at_utc"),
    ComputeJobStatus.RUNNING.value: ("started_at_utc", "leased_at_utc", "created_at_utc"),
    ComputeJobStatus.FAILED.value: ("completed_at_utc", "created_at_utc"),
}


class Base(DeclarativeBase):
    pass


class ComputeJobModel(Base):
    __tablename__ = "analytics_compute_job"
    __table_args__ = (
        Index("ix_compute_job_status_created_at", "job_status", "created_at_utc"),
        Index("ix_compute_job_status_analytics_type_created_at", "job_status", "analytics_type", "created_at_utc"),
        Index("ix_compute_job_status_lease_expiry", "job_status", "lease_expires_at_utc"),
        Index("ix_compute_job_terminal_retention", "job_status", "completed_at_utc", "created_at_utc"),
    )

    calculation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analytics_type: Mapped[str] = mapped_column(String(64), nullable=False)
    job_status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    leased_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass(frozen=True)
class ComputeJobRecord:
    calculation_id: UUID
    analytics_type: str
    job_status: ComputeJobStatus
    request_payload: dict[str, Any]
    response_payload: dict[str, Any] | None
    error_message: str | None
    error_type: str | None
    attempt_count: int
    max_attempts: int
    worker_id: str | None
    leased_at_utc: str | None
    lease_expires_at_utc: str | None
    last_error_at_utc: str | None
    created_at_utc: str
    started_at_utc: str | None
    completed_at_utc: str | None


@dataclass(frozen=True)
class ReconciledJobRecord:
    calculation_id: UUID
    analytics_type: str
    previous_status: ComputeJobStatus
    reconciled_status: ComputeJobStatus
    attempt_count: int
    max_attempts: int
    error_message: str
    error_type: str


@dataclass(frozen=True)
class _StaleJobReconciliationOutcome:
    job_status: ComputeJobStatus
    error_message: str
    error_type: str
    completed_at_utc: datetime | None


@dataclass(frozen=True)
class _ComputeJobRecordPayloadState:
    job_status: ComputeJobStatus
    request_payload: dict[str, Any]
    response_payload: dict[str, Any] | None
    error_message: str | None
    error_type: str | None


@dataclass(frozen=True)
class _ComputeJobPayloadFailure:
    request_payload: dict[str, Any] | None
    error_message: str
    error_type: str


@dataclass(frozen=True)
class _ComputeInspectionStatements:
    count_statement: Any
    items_statement: Any


@dataclass(frozen=True)
class _ComputeRecoveryQueryFilters:
    analytics_type: str | None
    calculation_id_contains: str | None
    recovered_after: datetime | None
    recovered_before: datetime | None
    cursor_recovered_before: datetime | None
    cursor_calculation_id_before: str | None


@dataclass(frozen=True)
class ComputeQueueStats:
    pending_count: int
    leased_count: int
    running_count: int
    failed_count: int
    complete_count: int
    retry_backlog_count: int
    lease_expired_count: int
    terminal_failure_count: int
    oldest_pending_age_seconds: float
    oldest_leased_age_seconds: float
    oldest_running_age_seconds: float
    reclaimable_count: int = 0


def _stale_job_reconciliation_outcome(
    *,
    previous_status: ComputeJobStatus,
    attempt_count: int,
    max_attempts: int,
    now: datetime,
) -> _StaleJobReconciliationOutcome:
    exhausted_retries = previous_status == ComputeJobStatus.RUNNING and attempt_count >= max_attempts
    if exhausted_retries:
        return _StaleJobReconciliationOutcome(
            job_status=ComputeJobStatus.FAILED,
            error_message="Compute job execution lease expired after exhausting retry budget.",
            error_type="LeaseExpired",
            completed_at_utc=now,
        )
    return _StaleJobReconciliationOutcome(
        job_status=ComputeJobStatus.PENDING,
        error_message="Compute job reconciliation detected an expired worker lease.",
        error_type="LeaseExpired",
        completed_at_utc=None,
    )


def _aggregate_row_count(aggregate_row: Any, field_name: str) -> int:
    return int(getattr(aggregate_row, field_name) or 0)


def _compute_job_status_count_column(*, status: ComputeJobStatus, label: str) -> Any:
    return func.sum(case((ComputeJobModel.job_status == status.value, 1), else_=0)).label(label)


def _compute_job_retry_backlog_count_column() -> Any:
    return func.sum(
        case(
            (
                (ComputeJobModel.job_status == ComputeJobStatus.PENDING.value) & (ComputeJobModel.attempt_count > 0),
                1,
            ),
            else_=0,
        )
    ).label("retry_backlog_count")


def _compute_job_reclaimable_count_column(*, now: datetime) -> Any:
    return func.sum(
        case(
            (
                ComputeJobModel.job_status.in_([ComputeJobStatus.LEASED.value, ComputeJobStatus.RUNNING.value])
                & ComputeJobModel.lease_expires_at_utc.is_not(None)
                & (ComputeJobModel.lease_expires_at_utc < now),
                1,
            ),
            else_=0,
        )
    ).label("reclaimable_count")


def _compute_job_terminal_failure_count_column() -> Any:
    return func.sum(
        case(
            (
                (ComputeJobModel.job_status == ComputeJobStatus.FAILED.value)
                & (ComputeJobModel.error_type != "LeaseExpired"),
                1,
            ),
            else_=0,
        )
    ).label("terminal_failure_count")


def _compute_job_oldest_timestamp_column(*, status: ComputeJobStatus, timestamp_field: Any, label: str) -> Any:
    return func.min(case((ComputeJobModel.job_status == status.value, timestamp_field))).label(label)


def _compute_job_terminal_retention_filter(cutoff: datetime) -> Any:
    return (
        ComputeJobModel.job_status.in_(COMPUTE_TERMINAL_JOB_STATUSES)
        & ComputeJobModel.completed_at_utc.is_not(None)
        & (ComputeJobModel.completed_at_utc <= cutoff)
    )


def _compute_queue_stats_columns(*, now: datetime) -> tuple[Any, ...]:
    return (
        _compute_job_status_count_column(status=ComputeJobStatus.PENDING, label="pending_count"),
        _compute_job_status_count_column(status=ComputeJobStatus.LEASED, label="leased_count"),
        _compute_job_status_count_column(status=ComputeJobStatus.RUNNING, label="running_count"),
        _compute_job_status_count_column(status=ComputeJobStatus.FAILED, label="failed_count"),
        _compute_job_status_count_column(status=ComputeJobStatus.COMPLETE, label="complete_count"),
        _compute_job_retry_backlog_count_column(),
        func.sum(case((ComputeJobModel.error_type == "LeaseExpired", 1), else_=0)).label("lease_expired_count"),
        _compute_job_reclaimable_count_column(now=now),
        _compute_job_terminal_failure_count_column(),
        _compute_job_oldest_timestamp_column(
            status=ComputeJobStatus.PENDING,
            timestamp_field=ComputeJobModel.created_at_utc,
            label="oldest_pending_created_at",
        ),
        _compute_job_oldest_timestamp_column(
            status=ComputeJobStatus.LEASED,
            timestamp_field=ComputeJobModel.leased_at_utc,
            label="oldest_leased_at",
        ),
        _compute_job_oldest_timestamp_column(
            status=ComputeJobStatus.RUNNING,
            timestamp_field=ComputeJobModel.started_at_utc,
            label="oldest_running_at",
        ),
    )


def _queue_stats_from_aggregate_row(*, aggregate_row: Any, stats_now: datetime) -> ComputeQueueStats:
    return ComputeQueueStats(
        pending_count=_aggregate_row_count(aggregate_row, "pending_count"),
        leased_count=_aggregate_row_count(aggregate_row, "leased_count"),
        running_count=_aggregate_row_count(aggregate_row, "running_count"),
        failed_count=_aggregate_row_count(aggregate_row, "failed_count"),
        complete_count=_aggregate_row_count(aggregate_row, "complete_count"),
        retry_backlog_count=_aggregate_row_count(aggregate_row, "retry_backlog_count"),
        lease_expired_count=_aggregate_row_count(aggregate_row, "lease_expired_count"),
        terminal_failure_count=_aggregate_row_count(aggregate_row, "terminal_failure_count"),
        oldest_pending_age_seconds=elapsed_seconds_since_or_zero(
            stats_now,
            aggregate_row.oldest_pending_created_at,
        ),
        oldest_leased_age_seconds=elapsed_seconds_since_or_zero(stats_now, aggregate_row.oldest_leased_at),
        oldest_running_age_seconds=elapsed_seconds_since_or_zero(stats_now, aggregate_row.oldest_running_at),
        reclaimable_count=_aggregate_row_count(aggregate_row, "reclaimable_count"),
    )


@dataclass(frozen=True)
class ComputeQueueInspectionAnchors:
    oldest_pending_calculation_id: str | None
    oldest_leased_calculation_id: str | None
    oldest_running_calculation_id: str | None
    latest_terminal_failure_calculation_id: str | None
    latest_recovered_calculation_id: str | None


@dataclass(frozen=True)
class ComputeQueueInspectionItem:
    calculation_id: str
    analytics_type: str
    status: str
    active_since_utc: str | None
    age_seconds: float | None
    attempt_count: int
    max_attempts: int
    error_type: str | None
    error_message: str | None


@dataclass(frozen=True)
class ComputeQueueInspectionPage:
    total_count: int
    next_offset: int | None
    items: list[ComputeQueueInspectionItem]


@dataclass(frozen=True)
class ComputeRecoveryEvent:
    calculation_id: str
    analytics_type: str
    recovery_kind: str
    recovered_at_utc: str
    attempt_count: int
    error_type: str | None


@dataclass(frozen=True)
class ComputeRecoveryEventPage:
    total_count: int
    next_offset: int | None
    next_cursor_recovered_before: str | None
    next_cursor_calculation_id_before: str | None
    items: list[ComputeRecoveryEvent]


@dataclass(frozen=True)
class ComputeJobRegistrationResult:
    status: ComputeJobRegistrationStatus
    existing_status: ComputeJobStatus | None = None


def _matches_existing_compute_job_registration(
    existing: ComputeJobModel,
    *,
    analytics_type: str,
    request_identity_json: str,
    max_attempts: int,
) -> bool:
    return (
        existing.analytics_type == analytics_type
        and _compute_job_request_identity_json_from_json(existing.request_json) == request_identity_json
        and existing.max_attempts == max_attempts
    )


def _compute_job_request_identity_json(request_payload: dict[str, Any]) -> str:
    identity_payload = {
        field: value for field, value in request_payload.items() if field not in TRANSIENT_COMPUTE_JOB_REQUEST_FIELDS
    }
    return json.dumps(identity_payload, sort_keys=True)


def _compute_job_request_identity_json_from_json(request_json: str) -> str:
    try:
        request_payload = json.loads(request_json)
    except json.JSONDecodeError:
        return request_json
    if not isinstance(request_payload, dict):
        return request_json
    return _compute_job_request_identity_json(request_payload)


def _compute_job_has_conflicting_worker_lease(
    *, current_worker_id: str | None, requested_worker_id: str | None
) -> bool:
    return requested_worker_id is not None and current_worker_id not in {None, requested_worker_id}


def _utc_aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ensure_compute_job_active_lease_owner(
    row: ComputeJobModel,
    *,
    calculation_id: UUID,
    worker_id: str | None,
    transition: str,
    now: datetime,
) -> None:
    if worker_id is None:
        return
    if row.job_status not in {ComputeJobStatus.LEASED.value, ComputeJobStatus.RUNNING.value}:
        raise ComputeJobLeaseOwnershipError(
            f"Cannot {transition} compute job without an active lease: {calculation_id}"
        )
    if row.worker_id != worker_id:
        raise ComputeJobLeaseOwnershipError(
            f"Compute job lease owner mismatch while trying to {transition}: {calculation_id}"
        )
    if row.lease_expires_at_utc is None:
        raise ComputeJobLeaseOwnershipError(f"Cannot {transition} compute job without a lease expiry: {calculation_id}")
    if _utc_aware_timestamp(row.lease_expires_at_utc) < now:
        raise ComputeJobLeaseOwnershipError(f"Cannot {transition} compute job after lease expiry: {calculation_id}")


def _compute_job_registration_result_for_integrity_conflict(
    existing: ComputeJobModel | None,
    *,
    integrity_error: IntegrityError,
    analytics_type: str,
    request_identity_json: str,
    max_attempts: int,
) -> ComputeJobRegistrationResult:
    if existing is None:
        raise integrity_error
    if _matches_existing_compute_job_registration(
        existing,
        analytics_type=analytics_type,
        request_identity_json=request_identity_json,
        max_attempts=max_attempts,
    ):
        return ComputeJobRegistrationResult(
            status=ComputeJobRegistrationStatus.REPLAY,
            existing_status=ComputeJobStatus(existing.job_status),
        )
    return ComputeJobRegistrationResult(
        status=ComputeJobRegistrationStatus.CONFLICT,
        existing_status=ComputeJobStatus(existing.job_status),
    )


def _recovery_seek_cursor_filter(
    *,
    cursor_recovered_before: datetime,
    cursor_calculation_id_before: str | None,
):
    cursor_filter = ComputeJobModel.last_error_at_utc < cursor_recovered_before
    if cursor_calculation_id_before:
        cursor_filter = cursor_filter | (
            (ComputeJobModel.last_error_at_utc == cursor_recovered_before)
            & (ComputeJobModel.calculation_id < cursor_calculation_id_before)
        )
    return cursor_filter


def _compute_recovery_query_filters(
    *,
    dialect_name: str,
    analytics_type: str | None,
    calculation_id_contains: str | None,
    recovered_after: datetime | None,
    recovered_before: datetime | None,
    cursor_recovered_before: datetime | None,
    cursor_calculation_id_before: str | None,
) -> _ComputeRecoveryQueryFilters:
    return _ComputeRecoveryQueryFilters(
        analytics_type=analytics_type,
        calculation_id_contains=calculation_id_contains,
        recovered_after=normalize_filter_datetime(recovered_after, dialect_name=dialect_name),
        recovered_before=normalize_filter_datetime(recovered_before, dialect_name=dialect_name),
        cursor_recovered_before=normalize_filter_datetime(cursor_recovered_before, dialect_name=dialect_name),
        cursor_calculation_id_before=cursor_calculation_id_before,
    )


def _compute_recovery_event_page(
    *,
    events: list[ComputeRecoveryEvent],
    total_count: int,
    offset: int,
) -> ComputeRecoveryEventPage:
    next_offset = next_offset_or_none(offset=offset, item_count=len(events), total_count=total_count)
    cursor = recovery_cursor_or_none(next_offset=next_offset, items=events)
    return ComputeRecoveryEventPage(
        total_count=total_count,
        next_offset=next_offset,
        next_cursor_recovered_before=cursor.recovered_before,
        next_cursor_calculation_id_before=cursor.calculation_id_before,
        items=events,
    )


def _ensure_compute_job_can_mark_running(
    row: ComputeJobModel,
    *,
    calculation_id: UUID,
    worker_id: str | None,
) -> None:
    if row.job_status == ComputeJobStatus.FAILED.value:
        raise ValueError(f"Cannot mark failed job as running: {calculation_id}")
    if row.job_status == ComputeJobStatus.COMPLETE.value:
        raise ValueError(f"Cannot mark complete job as running: {calculation_id}")
    if _compute_job_has_conflicting_worker_lease(current_worker_id=row.worker_id, requested_worker_id=worker_id):
        raise ValueError(f"Compute job leased by another worker: {calculation_id}")


class ComputeJobStore:
    def __init__(self, database_url: str):
        self._engine = create_durable_database_engine(database_url)
        self._session_factory = sessionmaker(bind=self._engine, future=True)

    def create_schema(self) -> None:
        Base.metadata.create_all(self._engine)
        self._ensure_runtime_indexes()

    @contextmanager
    def _session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def clear_all_records(self) -> None:
        with self._session() as session:
            session.query(ComputeJobModel).delete()

    def prune_terminal_jobs_older_than(self, older_than: datetime, *, dry_run: bool = False) -> int:
        with self._session() as session:
            cutoff = cast(
                datetime,
                normalize_filter_datetime(
                    older_than,
                    dialect_name=session.bind.dialect.name if session.bind is not None else "",
                ),
            )
            retention_filter = _compute_job_terminal_retention_filter(cutoff)
            if dry_run:
                statement = select(func.count()).select_from(ComputeJobModel).where(retention_filter)
                return int(session.execute(statement).scalar_one())
            result = session.execute(delete(ComputeJobModel).where(retention_filter))
            return int(result.rowcount or 0)

    def _ensure_runtime_indexes(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_compute_job_terminal_retention "
                    "ON analytics_compute_job (job_status, completed_at_utc, created_at_utc)"
                )
            )

    def enqueue_job(
        self,
        *,
        calculation_id: UUID,
        analytics_type: str,
        request_payload: dict[str, Any],
        max_attempts: int | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        configured_max_attempts = max_attempts or get_settings().COMPUTE_EXECUTOR_MAX_ATTEMPTS
        with self._session() as session:
            session.merge(
                ComputeJobModel(
                    calculation_id=str(calculation_id),
                    analytics_type=analytics_type,
                    job_status=ComputeJobStatus.PENDING.value,
                    request_json=json.dumps(request_payload, sort_keys=True),
                    response_json=None,
                    error_message=None,
                    error_type=None,
                    attempt_count=0,
                    max_attempts=configured_max_attempts,
                    worker_id=None,
                    leased_at_utc=None,
                    lease_expires_at_utc=None,
                    last_error_at_utc=None,
                    created_at_utc=now,
                    started_at_utc=None,
                    completed_at_utc=None,
                )
            )

    def register_job(
        self,
        *,
        calculation_id: UUID,
        analytics_type: str,
        request_payload: dict[str, Any],
        max_attempts: int | None = None,
    ) -> ComputeJobRegistrationResult:
        now = datetime.now(timezone.utc)
        configured_max_attempts = max_attempts or get_settings().COMPUTE_EXECUTOR_MAX_ATTEMPTS
        request_json = json.dumps(request_payload, sort_keys=True)
        request_identity_json = _compute_job_request_identity_json(request_payload)
        job = ComputeJobModel(
            calculation_id=str(calculation_id),
            analytics_type=analytics_type,
            job_status=ComputeJobStatus.PENDING.value,
            request_json=request_json,
            response_json=None,
            error_message=None,
            error_type=None,
            attempt_count=0,
            max_attempts=configured_max_attempts,
            worker_id=None,
            leased_at_utc=None,
            lease_expires_at_utc=None,
            last_error_at_utc=None,
            created_at_utc=now,
            started_at_utc=None,
            completed_at_utc=None,
        )

        session = self._session_factory()
        try:
            session.add(job)
            session.commit()
            return ComputeJobRegistrationResult(status=ComputeJobRegistrationStatus.CREATED)
        except IntegrityError as exc:
            session.rollback()
            existing = session.get(ComputeJobModel, str(calculation_id))
            return _compute_job_registration_result_for_integrity_conflict(
                existing,
                integrity_error=exc,
                analytics_type=analytics_type,
                request_identity_json=request_identity_json,
                max_attempts=configured_max_attempts,
            )
        finally:
            session.close()

    def list_pending_jobs(self, *, analytics_type: str | None = None, limit: int = 10) -> list[ComputeJobRecord]:
        with self._session() as session:
            statement = select(ComputeJobModel).where(ComputeJobModel.job_status == ComputeJobStatus.PENDING.value)
            if analytics_type is not None:
                statement = statement.where(ComputeJobModel.analytics_type == analytics_type)
            statement = statement.order_by(ComputeJobModel.created_at_utc.asc()).limit(limit)
            rows = session.execute(statement).scalars().all()
            return [self._to_record(row) for row in rows]

    def lease_pending_jobs(
        self,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int,
        analytics_type: str | None = None,
    ) -> list[ComputeJobRecord]:
        now = datetime.now(timezone.utc)
        lease_expiry = now + timedelta(seconds=lease_seconds)
        with self._session() as session:
            statement = self._build_lease_pending_jobs_statement(
                now=now,
                limit=limit,
                analytics_type=analytics_type,
                dialect_name=session.bind.dialect.name if session.bind is not None else "",
            )
            rows = session.execute(statement).scalars().all()
            leased: list[ComputeJobRecord] = []
            for row in rows:
                if _load_request_payload(row) is None:
                    _mark_invalid_request_payload(row, now=now)
                    continue
                row.job_status = ComputeJobStatus.LEASED.value
                row.worker_id = worker_id
                row.leased_at_utc = now
                row.lease_expires_at_utc = lease_expiry
                row.completed_at_utc = None
                leased.append(self._to_record(row))
            return leased

    def mark_running(
        self, calculation_id: UUID, *, worker_id: str | None = None, lease_seconds: int | None = None
    ) -> None:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            _ensure_compute_job_can_mark_running(row, calculation_id=calculation_id, worker_id=worker_id)
            row.job_status = ComputeJobStatus.RUNNING.value
            row.attempt_count += 1
            row.error_message = None
            row.error_type = None
            now = datetime.now(timezone.utc)
            row.started_at_utc = row.started_at_utc or now
            row.leased_at_utc = now
            row.lease_expires_at_utc = (
                now + timedelta(seconds=lease_seconds) if lease_seconds is not None else row.lease_expires_at_utc
            )
            row.completed_at_utc = None

    def ensure_active_lease_owner(self, calculation_id: UUID, *, worker_id: str | None) -> None:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            _ensure_compute_job_active_lease_owner(
                row,
                calculation_id=calculation_id,
                worker_id=worker_id,
                transition="publish success for",
                now=datetime.now(timezone.utc),
            )

    def mark_complete(
        self, calculation_id: UUID, *, response_payload: dict[str, Any], worker_id: str | None = None
    ) -> None:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            now = datetime.now(timezone.utc)
            _ensure_compute_job_active_lease_owner(
                row,
                calculation_id=calculation_id,
                worker_id=worker_id,
                transition="mark complete",
                now=now,
            )
            row.job_status = ComputeJobStatus.COMPLETE.value
            row.response_json = json.dumps(response_payload, sort_keys=True)
            row.error_message = None
            row.error_type = None
            row.started_at_utc = row.started_at_utc or now
            row.completed_at_utc = now
            row.leased_at_utc = None
            row.lease_expires_at_utc = None

    def mark_failed(
        self,
        calculation_id: UUID,
        *,
        error_message: str,
        error_type: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            now = datetime.now(timezone.utc)
            _ensure_compute_job_active_lease_owner(
                row,
                calculation_id=calculation_id,
                worker_id=worker_id,
                transition="mark failed",
                now=now,
            )
            row.job_status = ComputeJobStatus.FAILED.value
            row.error_message = error_message
            row.error_type = error_type
            row.started_at_utc = row.started_at_utc or now
            row.completed_at_utc = now
            row.last_error_at_utc = now
            row.leased_at_utc = None
            row.lease_expires_at_utc = None

    def mark_retryable_failure(
        self,
        calculation_id: UUID,
        *,
        error_message: str,
        error_type: str | None = None,
        worker_id: str | None = None,
    ) -> bool:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            now = datetime.now(timezone.utc)
            _ensure_compute_job_active_lease_owner(
                row,
                calculation_id=calculation_id,
                worker_id=worker_id,
                transition="mark retryable failure for",
                now=now,
            )
            row.error_message = error_message
            row.error_type = error_type
            row.last_error_at_utc = now
            row.leased_at_utc = None
            row.lease_expires_at_utc = None
            row.completed_at_utc = None
            if row.attempt_count < row.max_attempts:
                row.job_status = ComputeJobStatus.PENDING.value
                return True
            row.job_status = ComputeJobStatus.FAILED.value
            row.completed_at_utc = now
            return False

    def reconcile_stale_jobs(self, *, now: datetime | None = None) -> list[ReconciledJobRecord]:
        reconcile_now = now or datetime.now(timezone.utc)
        reconciled: list[ReconciledJobRecord] = []
        with self._session() as session:
            statement = self._build_reconcile_stale_jobs_statement(
                now=reconcile_now,
                dialect_name=session.bind.dialect.name if session.bind is not None else "",
            )
            rows = session.execute(statement).scalars().all()
            for row in rows:
                reconciled.append(self._reconcile_stale_job_row(row, now=reconcile_now))
        return reconciled

    def _reconcile_stale_job_row(self, row: ComputeJobModel, *, now: datetime) -> ReconciledJobRecord:
        previous_status = ComputeJobStatus(row.job_status)
        outcome = _stale_job_reconciliation_outcome(
            previous_status=previous_status,
            attempt_count=row.attempt_count,
            max_attempts=row.max_attempts,
            now=now,
        )
        row.worker_id = None
        row.leased_at_utc = None
        row.lease_expires_at_utc = None
        row.last_error_at_utc = now
        row.error_message = outcome.error_message
        row.error_type = outcome.error_type
        row.completed_at_utc = outcome.completed_at_utc
        row.job_status = outcome.job_status.value
        return ReconciledJobRecord(
            calculation_id=UUID(row.calculation_id),
            analytics_type=row.analytics_type,
            previous_status=previous_status,
            reconciled_status=ComputeJobStatus(row.job_status),
            attempt_count=row.attempt_count,
            max_attempts=row.max_attempts,
            error_message=outcome.error_message,
            error_type=outcome.error_type,
        )

    def _build_lease_pending_jobs_statement(
        self,
        *,
        now: datetime,
        limit: int,
        analytics_type: str | None,
        dialect_name: str,
    ):
        statement = select(ComputeJobModel).where(
            (ComputeJobModel.job_status == ComputeJobStatus.PENDING.value)
            | (
                (ComputeJobModel.job_status == ComputeJobStatus.LEASED.value)
                & (ComputeJobModel.lease_expires_at_utc.is_not(None))
                & (ComputeJobModel.lease_expires_at_utc < now)
            )
        )
        if analytics_type is not None:
            statement = statement.where(ComputeJobModel.analytics_type == analytics_type)
        statement = statement.order_by(ComputeJobModel.created_at_utc.asc()).limit(limit)
        if dialect_name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        return statement

    def _build_reconcile_stale_jobs_statement(self, *, now: datetime, dialect_name: str):
        statement = select(ComputeJobModel).where(
            (ComputeJobModel.job_status.in_([ComputeJobStatus.LEASED.value, ComputeJobStatus.RUNNING.value]))
            & (ComputeJobModel.lease_expires_at_utc.is_not(None))
            & (ComputeJobModel.lease_expires_at_utc < now)
        )
        if dialect_name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        return statement

    def get_job(self, calculation_id: UUID) -> ComputeJobRecord | None:
        with self._session() as session:
            row = session.get(ComputeJobModel, str(calculation_id))
            return None if row is None else self._to_record(row)

    def get_queue_stats(self, *, now: datetime | None = None) -> ComputeQueueStats:
        stats_now = now or datetime.now(timezone.utc)
        with self._session() as session:
            aggregate_row = session.execute(self._build_queue_stats_statement(now=stats_now)).one()
            return _queue_stats_from_aggregate_row(aggregate_row=aggregate_row, stats_now=stats_now)

    def get_queue_inspection_anchors(self) -> ComputeQueueInspectionAnchors:
        with self._session() as session:
            row = session.execute(self._build_queue_inspection_anchors_statement()).one()
            return ComputeQueueInspectionAnchors(
                oldest_pending_calculation_id=row.oldest_pending_calculation_id,
                oldest_leased_calculation_id=row.oldest_leased_calculation_id,
                oldest_running_calculation_id=row.oldest_running_calculation_id,
                latest_terminal_failure_calculation_id=row.latest_terminal_failure_calculation_id,
                latest_recovered_calculation_id=row.latest_recovered_calculation_id,
            )

    def list_recent_recoveries(
        self,
        *,
        limit: int = 5,
        offset: int = 0,
        analytics_type: str | None = None,
        calculation_id_contains: str | None = None,
        recovered_after: datetime | None = None,
        recovered_before: datetime | None = None,
        cursor_recovered_before: datetime | None = None,
        cursor_calculation_id_before: str | None = None,
    ) -> ComputeRecoveryEventPage:
        with self._session() as session:
            dialect_name = session.bind.dialect.name if session.bind is not None else ""
            filters = _compute_recovery_query_filters(
                dialect_name=dialect_name,
                analytics_type=analytics_type,
                calculation_id_contains=calculation_id_contains,
                recovered_after=recovered_after,
                recovered_before=recovered_before,
                cursor_recovered_before=cursor_recovered_before,
                cursor_calculation_id_before=cursor_calculation_id_before,
            )
            rows = (
                session.execute(
                    self._build_recent_recoveries_statement(
                        limit=limit,
                        offset=offset,
                        filters=filters,
                    )
                )
                .scalars()
                .all()
            )
            events = self._recovery_events_from_rows(rows)
            total_count = int(
                session.execute(
                    self._build_recent_recoveries_count_statement(
                        filters=filters,
                    )
                ).scalar_one()
                or 0
            )
            return _compute_recovery_event_page(events=events, total_count=total_count, offset=offset)

    def list_inspection_items(
        self,
        *,
        status_filter: str,
        limit: int,
        offset: int = 0,
        min_age_seconds: float = 0.0,
        analytics_type: str | None = None,
        calculation_id_contains: str | None = None,
        now: datetime | None = None,
    ) -> ComputeQueueInspectionPage:
        inspection_context = build_inspection_query_context(
            status_filter=status_filter,
            min_age_seconds=min_age_seconds,
            now=now,
        )

        with self._session() as session:
            statements = self._build_inspection_statements(
                inspection_context=inspection_context,
                limit=limit,
                offset=offset,
                analytics_type=analytics_type,
                calculation_id_contains=calculation_id_contains,
            )
            rows = session.execute(statements.items_statement).scalars().all()
            items = [self._to_inspection_item(row, now=inspection_context.now) for row in rows]
            total_count = int(session.execute(statements.count_statement).scalar_one() or 0)
            next_offset = next_offset_or_none(offset=offset, item_count=len(items), total_count=total_count)
            return ComputeQueueInspectionPage(total_count=total_count, next_offset=next_offset, items=items)

    def _build_inspection_statements(
        self,
        *,
        inspection_context: InspectionQueryContext,
        limit: int,
        offset: int,
        analytics_type: str | None,
        calculation_id_contains: str | None,
    ) -> _ComputeInspectionStatements:
        if inspection_context.status_filter == INSPECTION_STATUS_RECLAIMABLE:
            return self._build_reclaimable_inspection_statements(
                inspection_context=inspection_context,
                limit=limit,
                offset=offset,
                analytics_type=analytics_type,
                calculation_id_contains=calculation_id_contains,
            )
        return self._build_standard_inspection_statements(
            inspection_context=inspection_context,
            limit=limit,
            offset=offset,
            analytics_type=analytics_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_reclaimable_inspection_statements(
        self,
        *,
        inspection_context: InspectionQueryContext,
        limit: int,
        offset: int,
        analytics_type: str | None,
        calculation_id_contains: str | None,
    ) -> _ComputeInspectionStatements:
        return _ComputeInspectionStatements(
            count_statement=self._build_reclaimable_inspection_count_statement(
                analytics_type=analytics_type,
                calculation_id_contains=calculation_id_contains,
                now=inspection_context.now,
                min_age_threshold=inspection_context.min_age_threshold,
            ),
            items_statement=self._build_reclaimable_inspection_items_statement(
                limit=limit,
                offset=offset,
                analytics_type=analytics_type,
                calculation_id_contains=calculation_id_contains,
                now=inspection_context.now,
                min_age_threshold=inspection_context.min_age_threshold,
            ),
        )

    def _build_standard_inspection_statements(
        self,
        *,
        inspection_context: InspectionQueryContext,
        limit: int,
        offset: int,
        analytics_type: str | None,
        calculation_id_contains: str | None,
    ) -> _ComputeInspectionStatements:
        count_builder, items_builder = self._standard_inspection_statement_builders(inspection_context.status_filter)
        statement_arguments = {
            "analytics_type": analytics_type,
            "calculation_id_contains": calculation_id_contains,
            "min_age_threshold": inspection_context.min_age_threshold,
        }
        return _ComputeInspectionStatements(
            count_statement=count_builder(**statement_arguments),
            items_statement=items_builder(limit=limit, offset=offset, **statement_arguments),
        )

    def _standard_inspection_statement_builders(self, status_filter: str):
        statement_builders = {
            INSPECTION_STATUS_ACTIVE: (
                self._build_active_inspection_count_statement,
                self._build_active_inspection_items_statement,
            ),
            INSPECTION_STATUS_FAILED: (
                self._build_failed_inspection_count_statement,
                self._build_failed_inspection_items_statement,
            ),
            INSPECTION_STATUS_ALL: (
                self._build_all_inspection_count_statement,
                self._build_all_inspection_items_statement,
            ),
        }
        return statement_builders[status_filter]

    def _build_queue_stats_statement(self, *, now: datetime):
        return select(*_compute_queue_stats_columns(now=now))

    def _build_queue_inspection_anchors_statement(self):
        return select(
            select(ComputeJobModel.calculation_id)
            .where(ComputeJobModel.job_status == ComputeJobStatus.PENDING.value)
            .order_by(ComputeJobModel.created_at_utc.asc())
            .limit(1)
            .scalar_subquery()
            .label("oldest_pending_calculation_id"),
            select(ComputeJobModel.calculation_id)
            .where(ComputeJobModel.job_status == ComputeJobStatus.LEASED.value)
            .order_by(ComputeJobModel.leased_at_utc.asc(), ComputeJobModel.created_at_utc.asc())
            .limit(1)
            .scalar_subquery()
            .label("oldest_leased_calculation_id"),
            select(ComputeJobModel.calculation_id)
            .where(ComputeJobModel.job_status == ComputeJobStatus.RUNNING.value)
            .order_by(ComputeJobModel.started_at_utc.asc(), ComputeJobModel.created_at_utc.asc())
            .limit(1)
            .scalar_subquery()
            .label("oldest_running_calculation_id"),
            select(ComputeJobModel.calculation_id)
            .where(
                (ComputeJobModel.job_status == ComputeJobStatus.FAILED.value)
                & (ComputeJobModel.error_type != "LeaseExpired")
            )
            .order_by(ComputeJobModel.completed_at_utc.desc(), ComputeJobModel.created_at_utc.desc())
            .limit(1)
            .scalar_subquery()
            .label("latest_terminal_failure_calculation_id"),
            select(ComputeJobModel.calculation_id)
            .where(
                (ComputeJobModel.job_status == ComputeJobStatus.PENDING.value)
                & (ComputeJobModel.attempt_count > 0)
                & ComputeJobModel.last_error_at_utc.is_not(None)
            )
            .order_by(ComputeJobModel.last_error_at_utc.desc(), ComputeJobModel.created_at_utc.desc())
            .limit(1)
            .scalar_subquery()
            .label("latest_recovered_calculation_id"),
        )

    def _apply_calculation_filters(
        self,
        statement,
        *,
        analytics_type: str | None,
        calculation_id_contains: str | None,
    ):
        if analytics_type is not None:
            statement = statement.where(ComputeJobModel.analytics_type == analytics_type)
        return apply_calculation_id_prefix_filter(statement, ComputeJobModel.calculation_id, calculation_id_contains)

    @staticmethod
    def _apply_recovery_time_filters(
        statement,
        *,
        filters: _ComputeRecoveryQueryFilters,
    ):
        if filters.recovered_after is not None:
            statement = statement.where(ComputeJobModel.last_error_at_utc >= filters.recovered_after)
        if filters.recovered_before is not None:
            statement = statement.where(ComputeJobModel.last_error_at_utc <= filters.recovered_before)
        if filters.cursor_recovered_before is not None:
            statement = statement.where(
                _recovery_seek_cursor_filter(
                    cursor_recovered_before=filters.cursor_recovered_before,
                    cursor_calculation_id_before=filters.cursor_calculation_id_before,
                )
            )
        return statement

    def _build_recent_recoveries_statement(
        self,
        *,
        limit: int,
        offset: int,
        filters: _ComputeRecoveryQueryFilters,
    ):
        statement = (
            select(ComputeJobModel)
            .where(
                (ComputeJobModel.job_status == ComputeJobStatus.PENDING.value)
                & (ComputeJobModel.attempt_count > 0)
                & ComputeJobModel.last_error_at_utc.is_not(None)
            )
            .order_by(ComputeJobModel.last_error_at_utc.desc(), ComputeJobModel.calculation_id.desc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_recovery_time_filters(
            self._apply_calculation_filters(
                statement,
                analytics_type=filters.analytics_type,
                calculation_id_contains=filters.calculation_id_contains,
            ),
            filters=filters,
        )

    def _build_recent_recoveries_count_statement(
        self,
        *,
        filters: _ComputeRecoveryQueryFilters,
    ):
        statement = (
            select(func.count())
            .select_from(ComputeJobModel)
            .where(
                (ComputeJobModel.job_status == ComputeJobStatus.PENDING.value)
                & (ComputeJobModel.attempt_count > 0)
                & ComputeJobModel.last_error_at_utc.is_not(None)
            )
        )
        return self._apply_recovery_time_filters(
            self._apply_calculation_filters(
                statement,
                analytics_type=filters.analytics_type,
                calculation_id_contains=filters.calculation_id_contains,
            ),
            filters=filters,
        )

    @staticmethod
    def _build_active_since_expression():
        return case(
            (ComputeJobModel.job_status == ComputeJobStatus.RUNNING.value, ComputeJobModel.started_at_utc),
            (ComputeJobModel.job_status == ComputeJobStatus.LEASED.value, ComputeJobModel.leased_at_utc),
            (ComputeJobModel.job_status == ComputeJobStatus.FAILED.value, ComputeJobModel.completed_at_utc),
            else_=ComputeJobModel.created_at_utc,
        )

    def _apply_min_age_filter(self, statement, *, min_age_threshold: datetime | None):
        return apply_min_age_filter(
            statement,
            active_since=self._build_active_since_expression(),
            min_age_threshold=min_age_threshold,
        )

    def _build_active_inspection_items_statement(
        self,
        *,
        limit: int,
        offset: int,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        active_since = self._build_active_since_expression()
        statement = (
            select(ComputeJobModel)
            .where(ComputeJobModel.job_status.in_(COMPUTE_ACTIVE_INSPECTION_STATUSES))
            .order_by(active_since.asc(), ComputeJobModel.created_at_utc.asc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, min_age_threshold=min_age_threshold),
            analytics_type=analytics_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_failed_inspection_items_statement(
        self,
        *,
        limit: int,
        offset: int,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(ComputeJobModel)
            .where(ComputeJobModel.job_status == ComputeJobStatus.FAILED.value)
            .order_by(ComputeJobModel.completed_at_utc.desc(), ComputeJobModel.created_at_utc.desc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, min_age_threshold=min_age_threshold),
            analytics_type=analytics_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_all_inspection_items_statement(
        self,
        *,
        limit: int,
        offset: int,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        active_since = self._build_active_since_expression()
        statement = (
            select(ComputeJobModel)
            .order_by(active_since.asc().nullslast(), ComputeJobModel.created_at_utc.asc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, min_age_threshold=min_age_threshold),
            analytics_type=analytics_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_active_inspection_count_statement(
        self,
        *,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(func.count())
            .select_from(ComputeJobModel)
            .where(ComputeJobModel.job_status.in_(COMPUTE_ACTIVE_INSPECTION_STATUSES))
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, min_age_threshold=min_age_threshold),
            analytics_type=analytics_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_failed_inspection_count_statement(
        self,
        *,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(func.count())
            .select_from(ComputeJobModel)
            .where(ComputeJobModel.job_status == ComputeJobStatus.FAILED.value)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, min_age_threshold=min_age_threshold),
            analytics_type=analytics_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_all_inspection_count_statement(
        self,
        *,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = select(func.count()).select_from(ComputeJobModel)
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, min_age_threshold=min_age_threshold),
            analytics_type=analytics_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_reclaimable_inspection_items_statement(
        self,
        *,
        limit: int,
        offset: int,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        now: datetime,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(ComputeJobModel)
            .where(
                ComputeJobModel.job_status.in_(COMPUTE_RECLAIMABLE_INSPECTION_STATUSES)
                & ComputeJobModel.lease_expires_at_utc.is_not(None)
                & (ComputeJobModel.lease_expires_at_utc < now)
            )
            .order_by(ComputeJobModel.lease_expires_at_utc.asc(), ComputeJobModel.created_at_utc.asc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, min_age_threshold=min_age_threshold),
            analytics_type=analytics_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_reclaimable_inspection_count_statement(
        self,
        *,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        now: datetime,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(func.count())
            .select_from(ComputeJobModel)
            .where(
                ComputeJobModel.job_status.in_(COMPUTE_RECLAIMABLE_INSPECTION_STATUSES)
                & ComputeJobModel.lease_expires_at_utc.is_not(None)
                & (ComputeJobModel.lease_expires_at_utc < now)
            )
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, min_age_threshold=min_age_threshold),
            analytics_type=analytics_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _get_model(self, session: Session, calculation_id: UUID) -> ComputeJobModel:
        row = session.get(ComputeJobModel, str(calculation_id))
        if row is None:
            raise KeyError(f"Compute job not found: {calculation_id}")
        return row

    def _to_record(self, row: ComputeJobModel) -> ComputeJobRecord:
        request_payload = _load_request_payload(row)
        response_payload = _load_response_payload(row)
        payload_state = _compute_job_record_payload_state(
            row,
            request_payload=request_payload,
            response_payload=response_payload,
        )
        return ComputeJobRecord(
            calculation_id=UUID(row.calculation_id),
            analytics_type=row.analytics_type,
            job_status=payload_state.job_status,
            request_payload=payload_state.request_payload,
            response_payload=payload_state.response_payload,
            error_message=payload_state.error_message,
            error_type=payload_state.error_type,
            attempt_count=row.attempt_count,
            max_attempts=row.max_attempts,
            worker_id=row.worker_id,
            leased_at_utc=format_timestamp(row.leased_at_utc),
            lease_expires_at_utc=format_timestamp(row.lease_expires_at_utc),
            last_error_at_utc=format_timestamp(row.last_error_at_utc),
            created_at_utc=format_timestamp(row.created_at_utc) or "",
            started_at_utc=format_timestamp(row.started_at_utc),
            completed_at_utc=format_timestamp(row.completed_at_utc),
        )

    def _to_inspection_item(self, row: ComputeJobModel, *, now: datetime) -> ComputeQueueInspectionItem:
        active_since = self._inspection_active_since(row)

        age_seconds = None
        if active_since is not None:
            age_seconds = elapsed_seconds_since(now, active_since)

        return ComputeQueueInspectionItem(
            calculation_id=row.calculation_id,
            analytics_type=row.analytics_type,
            status=row.job_status,
            active_since_utc=format_timestamp(active_since),
            age_seconds=age_seconds,
            attempt_count=row.attempt_count,
            max_attempts=row.max_attempts,
            error_type=row.error_type,
            error_message=row.error_message,
        )

    @staticmethod
    def _inspection_active_since(row: ComputeJobModel) -> datetime | None:
        return _compute_job_inspection_active_since(row)

    def _to_recovery_event(self, row: ComputeJobModel) -> ComputeRecoveryEvent | None:
        recovered_at_utc = format_timestamp(row.last_error_at_utc)
        if recovered_at_utc is None:
            return None
        recovery_kind = "stale_lease_recovered" if row.error_type == "LeaseExpired" else "retryable_failure"
        return ComputeRecoveryEvent(
            calculation_id=row.calculation_id,
            analytics_type=row.analytics_type,
            recovery_kind=recovery_kind,
            recovered_at_utc=recovered_at_utc,
            attempt_count=row.attempt_count,
            error_type=row.error_type,
        )

    def _recovery_events_from_rows(self, rows: Iterable[ComputeJobModel]) -> list[ComputeRecoveryEvent]:
        events: list[ComputeRecoveryEvent] = []
        for row in rows:
            event = self._to_recovery_event(row)
            if event is None:
                continue
            events.append(event)
        return events


_store_cache: dict[str, ComputeJobStore] = {}


def get_compute_job_store(*, database_url: str | None = None) -> ComputeJobStore:
    return resolve_runtime_store(cache=_store_cache, factory=ComputeJobStore, database_url=database_url)


compute_job_store = RuntimeStoreProxy(get_compute_job_store)


def _compute_job_inspection_active_since(row: ComputeJobModel) -> datetime | None:
    field_names = COMPUTE_INSPECTION_ACTIVE_SINCE_FIELDS.get(row.job_status, ("created_at_utc",))
    return _first_datetime_field(row, field_names)


def _first_datetime_field(row: ComputeJobModel, field_names: tuple[str, ...]) -> datetime | None:
    for field_name in field_names:
        value = getattr(row, field_name)
        if value is not None:
            return value
    return None


def _compute_job_record_payload_state(
    row: ComputeJobModel,
    *,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
) -> _ComputeJobRecordPayloadState:
    job_status = ComputeJobStatus(row.job_status)
    error_message = row.error_message
    error_type = row.error_type
    payload_failure = _compute_job_payload_failure(
        row,
        request_payload=request_payload,
        response_payload=response_payload,
    )
    if payload_failure is not None:
        job_status = ComputeJobStatus.FAILED
        error_message = payload_failure.error_message
        error_type = payload_failure.error_type
        request_payload = payload_failure.request_payload
    if request_payload is None:
        raise RuntimeError("Compute job request payload resolution failed.")
    return _ComputeJobRecordPayloadState(
        job_status=job_status,
        request_payload=request_payload,
        response_payload=response_payload,
        error_message=error_message,
        error_type=error_type,
    )


def _compute_job_payload_failure(
    row: ComputeJobModel,
    *,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
) -> _ComputeJobPayloadFailure | None:
    if request_payload is None:
        return _invalid_compute_job_request_payload_failure(row)
    if _has_invalid_compute_job_response_payload(row, response_payload=response_payload):
        return _invalid_compute_job_response_payload_failure(row, request_payload=request_payload)
    return None


def _invalid_compute_job_request_payload_failure(row: ComputeJobModel) -> _ComputeJobPayloadFailure:
    return _ComputeJobPayloadFailure(
        request_payload={},
        error_message=_stored_or_default(row.error_message, INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_MESSAGE),
        error_type=_stored_or_default(row.error_type, INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_ERROR_TYPE),
    )


def _invalid_compute_job_response_payload_failure(
    row: ComputeJobModel,
    *,
    request_payload: dict[str, Any],
) -> _ComputeJobPayloadFailure:
    return _ComputeJobPayloadFailure(
        request_payload=request_payload,
        error_message=_stored_or_default(row.error_message, INVALID_COMPUTE_JOB_RESPONSE_PAYLOAD_MESSAGE),
        error_type=_stored_or_default(row.error_type, INVALID_COMPUTE_JOB_RESPONSE_PAYLOAD_ERROR_TYPE),
    )


def _has_invalid_compute_job_response_payload(
    row: ComputeJobModel,
    *,
    response_payload: dict[str, Any] | None,
) -> bool:
    if not row.response_json:
        return False
    return response_payload is None


def _stored_or_default(value: str | None, default: str) -> str:
    if value:
        return value
    return default


def _load_request_payload(row: ComputeJobModel) -> dict[str, Any] | None:
    return load_json_object_or_none(
        row.request_json,
        logger=logger,
        payload_name="Compute job request payload",
        identity_name="calculation_id",
        identity_value=row.calculation_id,
        empty_is_absent=False,
    )


def _load_response_payload(row: ComputeJobModel) -> dict[str, Any] | None:
    return load_json_object_or_none(
        row.response_json,
        logger=logger,
        payload_name="Compute job response payload",
        identity_name="calculation_id",
        identity_value=row.calculation_id,
    )


def _mark_invalid_request_payload(row: ComputeJobModel, *, now: datetime) -> None:
    row.job_status = ComputeJobStatus.FAILED.value
    row.error_message = row.error_message or INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_MESSAGE
    row.error_type = row.error_type or INVALID_COMPUTE_JOB_REQUEST_PAYLOAD_ERROR_TYPE
    row.worker_id = None
    row.leased_at_utc = None
    row.lease_expires_at_utc = None
    row.last_error_at_utc = now
    row.completed_at_utc = now
