from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings


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


@dataclass(frozen=True)
class ComputeJobRegistrationResult:
    status: ComputeJobRegistrationStatus
    existing_status: ComputeJobStatus | None = None


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
            counts_statement = select(ComputeJobModel.job_status, func.count()).group_by(ComputeJobModel.job_status)
            counts_rows = session.execute(counts_statement).all()
            counts = {status: count for status, count in counts_rows}
            pressure_rows = session.execute(
                select(
                    ComputeJobModel.job_status,
                    ComputeJobModel.error_type,
                    ComputeJobModel.attempt_count,
                )
            ).all()
            retry_backlog_count = sum(
                1
                for job_status, _error_type, attempt_count in pressure_rows
                if job_status == ComputeJobStatus.PENDING.value and attempt_count > 0
            )
            lease_expired_count = sum(
                1 for _job_status, error_type, _attempt_count in pressure_rows if error_type == "LeaseExpired"
            )
            terminal_failure_count = sum(
                1
                for job_status, error_type, _attempt_count in pressure_rows
                if job_status == ComputeJobStatus.FAILED.value and error_type != "LeaseExpired"
            )

            oldest_pending_created_at = session.execute(
                select(func.min(ComputeJobModel.created_at_utc)).where(
                    ComputeJobModel.job_status == ComputeJobStatus.PENDING.value
                )
            ).scalar_one()
            oldest_leased_started_at = session.execute(
                select(func.min(ComputeJobModel.leased_at_utc)).where(
                    ComputeJobModel.job_status == ComputeJobStatus.LEASED.value
                )
            ).scalar_one()
            oldest_running_started_at = session.execute(
                select(func.min(ComputeJobModel.started_at_utc)).where(
                    ComputeJobModel.job_status == ComputeJobStatus.RUNNING.value
                )
            ).scalar_one()

            oldest_pending_age_seconds = 0.0
            if oldest_pending_created_at is not None:
                oldest_pending_age_seconds = max(
                    0.0,
                    (stats_now - _coerce_utc_datetime(oldest_pending_created_at)).total_seconds(),
                )
            oldest_leased_age_seconds = 0.0
            if oldest_leased_started_at is not None:
                oldest_leased_age_seconds = max(
                    0.0,
                    (stats_now - _coerce_utc_datetime(oldest_leased_started_at)).total_seconds(),
                )
            oldest_running_age_seconds = 0.0
            if oldest_running_started_at is not None:
                oldest_running_age_seconds = max(
                    0.0,
                    (stats_now - _coerce_utc_datetime(oldest_running_started_at)).total_seconds(),
                )

            return ComputeQueueStats(
                pending_count=int(counts.get(ComputeJobStatus.PENDING.value, 0)),
                leased_count=int(counts.get(ComputeJobStatus.LEASED.value, 0)),
                running_count=int(counts.get(ComputeJobStatus.RUNNING.value, 0)),
                failed_count=int(counts.get(ComputeJobStatus.FAILED.value, 0)),
                complete_count=int(counts.get(ComputeJobStatus.COMPLETE.value, 0)),
                retry_backlog_count=retry_backlog_count,
                lease_expired_count=lease_expired_count,
                terminal_failure_count=terminal_failure_count,
                oldest_pending_age_seconds=oldest_pending_age_seconds,
                oldest_leased_age_seconds=oldest_leased_age_seconds,
                oldest_running_age_seconds=oldest_running_age_seconds,
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


settings = get_settings()
compute_job_store = ComputeJobStore(settings.LINEAGE_METADATA_DATABASE_URL)
