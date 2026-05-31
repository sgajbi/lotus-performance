from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text, case, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings
from app.services.durable_store_inspection import (
    INSPECTION_STATUS_ACTIVE,
    INSPECTION_STATUS_ALL,
    INSPECTION_STATUS_FAILED,
    INSPECTION_STATUS_RECLAIMABLE,
    apply_min_age_filter,
    build_inspection_query_context,
)
from app.services.durable_store_pagination import next_offset_or_none, recovery_cursor_or_none
from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store
from app.services.durable_store_time import (
    elapsed_seconds_since as _elapsed_seconds_since,
)
from app.services.durable_store_time import (
    elapsed_seconds_since_or_zero as _elapsed_seconds_since_or_zero,
)
from app.services.durable_store_time import (
    format_timestamp as _format_timestamp,
)
from app.services.durable_store_time import (
    normalize_filter_datetime as _normalize_filter_datetime,
)


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


class Base(DeclarativeBase):
    pass


class ComputeJobModel(Base):
    __tablename__ = "analytics_compute_job"
    __table_args__ = (
        Index("ix_compute_job_status_created_at", "job_status", "created_at_utc"),
        Index("ix_compute_job_status_analytics_type_created_at", "job_status", "analytics_type", "created_at_utc"),
        Index("ix_compute_job_status_lease_expiry", "job_status", "lease_expires_at_utc"),
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


class ComputeJobStore:
    def __init__(self, database_url: str):
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._session_factory = sessionmaker(bind=self._engine, future=True)

    def create_schema(self) -> None:
        Base.metadata.create_all(self._engine)

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
            cutoff = _normalize_filter_datetime(
                older_than,
                dialect_name=session.bind.dialect.name if session.bind is not None else "",
            )
            rows = (
                session.execute(
                    select(ComputeJobModel)
                    .where(
                        ComputeJobModel.job_status.in_([ComputeJobStatus.COMPLETE.value, ComputeJobStatus.FAILED.value])
                    )
                    .where(ComputeJobModel.completed_at_utc.is_not(None))
                    .where(ComputeJobModel.completed_at_utc <= cutoff)
                )
                .scalars()
                .all()
            )
            if dry_run:
                return len(rows)
            for row in rows:
                session.delete(row)
            return len(rows)

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
        except IntegrityError:
            session.rollback()
            existing = session.get(ComputeJobModel, str(calculation_id))
            if existing is None:
                raise
            if (
                existing.analytics_type == analytics_type
                and existing.request_json == request_json
                and existing.max_attempts == configured_max_attempts
            ):
                return ComputeJobRegistrationResult(
                    status=ComputeJobRegistrationStatus.REPLAY,
                    existing_status=ComputeJobStatus(existing.job_status),
                )
            return ComputeJobRegistrationResult(
                status=ComputeJobRegistrationStatus.CONFLICT,
                existing_status=ComputeJobStatus(existing.job_status),
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
            if row.job_status == ComputeJobStatus.FAILED.value:
                raise ValueError(f"Cannot mark failed job as running: {calculation_id}")
            if row.job_status == ComputeJobStatus.COMPLETE.value:
                raise ValueError(f"Cannot mark complete job as running: {calculation_id}")
            if worker_id is not None and row.worker_id not in {None, worker_id}:
                raise ValueError(f"Compute job leased by another worker: {calculation_id}")
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

    def mark_complete(self, calculation_id: UUID, *, response_payload: dict[str, Any]) -> None:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            now = datetime.now(timezone.utc)
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
    ) -> None:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            now = datetime.now(timezone.utc)
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
    ) -> bool:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            now = datetime.now(timezone.utc)
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
                previous_status = ComputeJobStatus(row.job_status)
                exhausted_retries = (
                    previous_status == ComputeJobStatus.RUNNING and row.attempt_count >= row.max_attempts
                )
                row.worker_id = None
                row.leased_at_utc = None
                row.lease_expires_at_utc = None
                row.last_error_at_utc = reconcile_now
                row.error_message = (
                    "Compute job reconciliation detected an expired worker lease."
                    if not exhausted_retries
                    else "Compute job execution lease expired after exhausting retry budget."
                )
                row.error_type = "LeaseExpired"
                row.completed_at_utc = reconcile_now if exhausted_retries else None
                row.job_status = ComputeJobStatus.FAILED.value if exhausted_retries else ComputeJobStatus.PENDING.value
                reconciled.append(
                    ReconciledJobRecord(
                        calculation_id=UUID(row.calculation_id),
                        analytics_type=row.analytics_type,
                        previous_status=previous_status,
                        reconciled_status=ComputeJobStatus(row.job_status),
                        attempt_count=row.attempt_count,
                        max_attempts=row.max_attempts,
                        error_message=row.error_message,
                        error_type=row.error_type or "LeaseExpired",
                    )
                )
        return reconciled

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

            return ComputeQueueStats(
                pending_count=int(aggregate_row.pending_count or 0),
                leased_count=int(aggregate_row.leased_count or 0),
                running_count=int(aggregate_row.running_count or 0),
                failed_count=int(aggregate_row.failed_count or 0),
                complete_count=int(aggregate_row.complete_count or 0),
                retry_backlog_count=int(aggregate_row.retry_backlog_count or 0),
                lease_expired_count=int(aggregate_row.lease_expired_count or 0),
                terminal_failure_count=int(aggregate_row.terminal_failure_count or 0),
                oldest_pending_age_seconds=_elapsed_seconds_since_or_zero(
                    stats_now,
                    aggregate_row.oldest_pending_created_at,
                ),
                oldest_leased_age_seconds=_elapsed_seconds_since_or_zero(stats_now, aggregate_row.oldest_leased_at),
                oldest_running_age_seconds=_elapsed_seconds_since_or_zero(stats_now, aggregate_row.oldest_running_at),
                reclaimable_count=int(aggregate_row.reclaimable_count or 0),
            )

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
            normalized_recovered_after = _normalize_filter_datetime(recovered_after, dialect_name=dialect_name)
            normalized_recovered_before = _normalize_filter_datetime(recovered_before, dialect_name=dialect_name)
            normalized_cursor_recovered_before = _normalize_filter_datetime(
                cursor_recovered_before,
                dialect_name=dialect_name,
            )
            rows = (
                session.execute(
                    self._build_recent_recoveries_statement(
                        limit=limit,
                        offset=offset,
                        analytics_type=analytics_type,
                        calculation_id_contains=calculation_id_contains,
                        recovered_after=normalized_recovered_after,
                        recovered_before=normalized_recovered_before,
                        cursor_recovered_before=normalized_cursor_recovered_before,
                        cursor_calculation_id_before=cursor_calculation_id_before,
                    )
                )
                .scalars()
                .all()
            )
            events: list[ComputeRecoveryEvent] = []
            for row in rows:
                event = self._to_recovery_event(row)
                if event is None:
                    continue
                events.append(event)
            total_count = int(
                session.execute(
                    self._build_recent_recoveries_count_statement(
                        analytics_type=analytics_type,
                        calculation_id_contains=calculation_id_contains,
                        recovered_after=normalized_recovered_after,
                        recovered_before=normalized_recovered_before,
                        cursor_recovered_before=normalized_cursor_recovered_before,
                        cursor_calculation_id_before=cursor_calculation_id_before,
                    )
                ).scalar_one()
                or 0
            )
            next_offset = next_offset_or_none(offset=offset, item_count=len(events), total_count=total_count)
            cursor = recovery_cursor_or_none(next_offset=next_offset, items=events)
            return ComputeRecoveryEventPage(
                total_count=total_count,
                next_offset=next_offset,
                next_cursor_recovered_before=cursor.recovered_before,
                next_cursor_calculation_id_before=cursor.calculation_id_before,
                items=events,
            )

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
            if inspection_context.status_filter == INSPECTION_STATUS_ACTIVE:
                count_statement = self._build_active_inspection_count_statement(
                    analytics_type=analytics_type,
                    calculation_id_contains=calculation_id_contains,
                    min_age_threshold=inspection_context.min_age_threshold,
                )
                statement = self._build_active_inspection_items_statement(
                    limit=limit,
                    offset=offset,
                    analytics_type=analytics_type,
                    calculation_id_contains=calculation_id_contains,
                    min_age_threshold=inspection_context.min_age_threshold,
                )
            elif inspection_context.status_filter == INSPECTION_STATUS_FAILED:
                count_statement = self._build_failed_inspection_count_statement(
                    analytics_type=analytics_type,
                    calculation_id_contains=calculation_id_contains,
                    min_age_threshold=inspection_context.min_age_threshold,
                )
                statement = self._build_failed_inspection_items_statement(
                    limit=limit,
                    offset=offset,
                    analytics_type=analytics_type,
                    calculation_id_contains=calculation_id_contains,
                    min_age_threshold=inspection_context.min_age_threshold,
                )
            elif inspection_context.status_filter == INSPECTION_STATUS_ALL:
                count_statement = self._build_all_inspection_count_statement(
                    analytics_type=analytics_type,
                    calculation_id_contains=calculation_id_contains,
                    min_age_threshold=inspection_context.min_age_threshold,
                )
                statement = self._build_all_inspection_items_statement(
                    limit=limit,
                    offset=offset,
                    analytics_type=analytics_type,
                    calculation_id_contains=calculation_id_contains,
                    min_age_threshold=inspection_context.min_age_threshold,
                )
            elif inspection_context.status_filter == INSPECTION_STATUS_RECLAIMABLE:
                count_statement = self._build_reclaimable_inspection_count_statement(
                    analytics_type=analytics_type,
                    calculation_id_contains=calculation_id_contains,
                    now=inspection_context.now,
                    min_age_threshold=inspection_context.min_age_threshold,
                )
                statement = self._build_reclaimable_inspection_items_statement(
                    limit=limit,
                    offset=offset,
                    analytics_type=analytics_type,
                    calculation_id_contains=calculation_id_contains,
                    now=inspection_context.now,
                    min_age_threshold=inspection_context.min_age_threshold,
                )
            else:
                raise ValueError(f"Unsupported status filter: {status_filter}")
            rows = session.execute(statement).scalars().all()
            items = [self._to_inspection_item(row, now=inspection_context.now) for row in rows]
            total_count = int(session.execute(count_statement).scalar_one() or 0)
            next_offset = next_offset_or_none(offset=offset, item_count=len(items), total_count=total_count)
            return ComputeQueueInspectionPage(total_count=total_count, next_offset=next_offset, items=items)

    def _build_queue_stats_statement(self, *, now: datetime):
        return select(
            func.sum(case((ComputeJobModel.job_status == ComputeJobStatus.PENDING.value, 1), else_=0)).label(
                "pending_count"
            ),
            func.sum(case((ComputeJobModel.job_status == ComputeJobStatus.LEASED.value, 1), else_=0)).label(
                "leased_count"
            ),
            func.sum(case((ComputeJobModel.job_status == ComputeJobStatus.RUNNING.value, 1), else_=0)).label(
                "running_count"
            ),
            func.sum(case((ComputeJobModel.job_status == ComputeJobStatus.FAILED.value, 1), else_=0)).label(
                "failed_count"
            ),
            func.sum(case((ComputeJobModel.job_status == ComputeJobStatus.COMPLETE.value, 1), else_=0)).label(
                "complete_count"
            ),
            func.sum(
                case(
                    (
                        (ComputeJobModel.job_status == ComputeJobStatus.PENDING.value)
                        & (ComputeJobModel.attempt_count > 0),
                        1,
                    ),
                    else_=0,
                )
            ).label("retry_backlog_count"),
            func.sum(case((ComputeJobModel.error_type == "LeaseExpired", 1), else_=0)).label("lease_expired_count"),
            func.sum(
                case(
                    (
                        ComputeJobModel.job_status.in_([ComputeJobStatus.LEASED.value, ComputeJobStatus.RUNNING.value])
                        & ComputeJobModel.lease_expires_at_utc.is_not(None)
                        & (ComputeJobModel.lease_expires_at_utc < now),
                        1,
                    ),
                    else_=0,
                )
            ).label("reclaimable_count"),
            func.sum(
                case(
                    (
                        (ComputeJobModel.job_status == ComputeJobStatus.FAILED.value)
                        & (ComputeJobModel.error_type != "LeaseExpired"),
                        1,
                    ),
                    else_=0,
                )
            ).label("terminal_failure_count"),
            func.min(
                case((ComputeJobModel.job_status == ComputeJobStatus.PENDING.value, ComputeJobModel.created_at_utc))
            ).label("oldest_pending_created_at"),
            func.min(
                case((ComputeJobModel.job_status == ComputeJobStatus.LEASED.value, ComputeJobModel.leased_at_utc))
            ).label("oldest_leased_at"),
            func.min(
                case((ComputeJobModel.job_status == ComputeJobStatus.RUNNING.value, ComputeJobModel.started_at_utc))
            ).label("oldest_running_at"),
        )

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
        if calculation_id_contains:
            statement = statement.where(ComputeJobModel.calculation_id.contains(calculation_id_contains))
        return statement

    @staticmethod
    def _apply_recovery_time_filters(
        statement,
        *,
        recovered_after: datetime | None,
        recovered_before: datetime | None,
        cursor_recovered_before: datetime | None,
        cursor_calculation_id_before: str | None,
    ):
        if recovered_after is not None:
            statement = statement.where(ComputeJobModel.last_error_at_utc >= recovered_after)
        if recovered_before is not None:
            statement = statement.where(ComputeJobModel.last_error_at_utc <= recovered_before)
        if cursor_recovered_before is not None:
            cursor_filter = ComputeJobModel.last_error_at_utc < cursor_recovered_before
            if cursor_calculation_id_before:
                cursor_filter = cursor_filter | (
                    (ComputeJobModel.last_error_at_utc == cursor_recovered_before)
                    & (ComputeJobModel.calculation_id < cursor_calculation_id_before)
                )
            statement = statement.where(cursor_filter)
        return statement

    def _build_recent_recoveries_statement(
        self,
        *,
        limit: int,
        offset: int,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        recovered_after: datetime | None,
        recovered_before: datetime | None,
        cursor_recovered_before: datetime | None,
        cursor_calculation_id_before: str | None,
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
                analytics_type=analytics_type,
                calculation_id_contains=calculation_id_contains,
            ),
            recovered_after=recovered_after,
            recovered_before=recovered_before,
            cursor_recovered_before=cursor_recovered_before,
            cursor_calculation_id_before=cursor_calculation_id_before,
        )

    def _build_recent_recoveries_count_statement(
        self,
        *,
        analytics_type: str | None,
        calculation_id_contains: str | None,
        recovered_after: datetime | None,
        recovered_before: datetime | None,
        cursor_recovered_before: datetime | None,
        cursor_calculation_id_before: str | None,
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
                analytics_type=analytics_type,
                calculation_id_contains=calculation_id_contains,
            ),
            recovered_after=recovered_after,
            recovered_before=recovered_before,
            cursor_recovered_before=cursor_recovered_before,
            cursor_calculation_id_before=cursor_calculation_id_before,
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
            .where(
                ComputeJobModel.job_status.in_(
                    [
                        ComputeJobStatus.PENDING.value,
                        ComputeJobStatus.LEASED.value,
                        ComputeJobStatus.RUNNING.value,
                    ]
                )
            )
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
            .where(
                ComputeJobModel.job_status.in_(
                    [
                        ComputeJobStatus.PENDING.value,
                        ComputeJobStatus.LEASED.value,
                        ComputeJobStatus.RUNNING.value,
                    ]
                )
            )
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
                ComputeJobModel.job_status.in_([ComputeJobStatus.LEASED.value, ComputeJobStatus.RUNNING.value])
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
                ComputeJobModel.job_status.in_([ComputeJobStatus.LEASED.value, ComputeJobStatus.RUNNING.value])
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
        return ComputeJobRecord(
            calculation_id=UUID(row.calculation_id),
            analytics_type=row.analytics_type,
            job_status=ComputeJobStatus(row.job_status),
            request_payload=json.loads(row.request_json),
            response_payload=json.loads(row.response_json) if row.response_json else None,
            error_message=row.error_message,
            error_type=row.error_type,
            attempt_count=row.attempt_count,
            max_attempts=row.max_attempts,
            worker_id=row.worker_id,
            leased_at_utc=_format_timestamp(row.leased_at_utc),
            lease_expires_at_utc=_format_timestamp(row.lease_expires_at_utc),
            last_error_at_utc=_format_timestamp(row.last_error_at_utc),
            created_at_utc=_format_timestamp(row.created_at_utc) or "",
            started_at_utc=_format_timestamp(row.started_at_utc),
            completed_at_utc=_format_timestamp(row.completed_at_utc),
        )

    def _to_inspection_item(self, row: ComputeJobModel, *, now: datetime) -> ComputeQueueInspectionItem:
        active_since = self._inspection_active_since(row)

        age_seconds = None
        if active_since is not None:
            age_seconds = _elapsed_seconds_since(now, active_since)

        return ComputeQueueInspectionItem(
            calculation_id=row.calculation_id,
            analytics_type=row.analytics_type,
            status=row.job_status,
            active_since_utc=_format_timestamp(active_since),
            age_seconds=age_seconds,
            attempt_count=row.attempt_count,
            max_attempts=row.max_attempts,
            error_type=row.error_type,
            error_message=row.error_message,
        )

    @staticmethod
    def _inspection_active_since(row: ComputeJobModel) -> datetime | None:
        if row.job_status == ComputeJobStatus.LEASED.value:
            return row.leased_at_utc or row.created_at_utc
        if row.job_status == ComputeJobStatus.RUNNING.value:
            return row.started_at_utc or row.leased_at_utc or row.created_at_utc
        if row.job_status == ComputeJobStatus.FAILED.value:
            return row.completed_at_utc or row.created_at_utc
        return row.created_at_utc

    def _to_recovery_event(self, row: ComputeJobModel) -> ComputeRecoveryEvent | None:
        recovered_at_utc = _format_timestamp(row.last_error_at_utc)
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


_store_cache: dict[str, ComputeJobStore] = {}


def get_compute_job_store(*, database_url: str | None = None) -> ComputeJobStore:
    return resolve_runtime_store(cache=_store_cache, factory=ComputeJobStore, database_url=database_url)


compute_job_store = RuntimeStoreProxy(get_compute_job_store)
