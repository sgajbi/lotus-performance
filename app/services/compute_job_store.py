from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings


class ComputeJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class Base(DeclarativeBase):
    pass


class ComputeJobModel(Base):
    __tablename__ = "analytics_compute_job"

    calculation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analytics_type: Mapped[str] = mapped_column(String(64), nullable=False)
    job_status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    attempt_count: int
    created_at_utc: str
    started_at_utc: str | None
    completed_at_utc: str | None


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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

    def enqueue_job(self, *, calculation_id: UUID, analytics_type: str, request_payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        with self._session() as session:
            session.merge(
                ComputeJobModel(
                    calculation_id=str(calculation_id),
                    analytics_type=analytics_type,
                    job_status=ComputeJobStatus.PENDING.value,
                    request_json=json.dumps(request_payload, sort_keys=True),
                    response_json=None,
                    error_message=None,
                    attempt_count=0,
                    created_at_utc=now,
                    started_at_utc=None,
                    completed_at_utc=None,
                )
            )

    def list_pending_jobs(self, *, analytics_type: str | None = None, limit: int = 10) -> list[ComputeJobRecord]:
        with self._session() as session:
            statement = select(ComputeJobModel).where(ComputeJobModel.job_status == ComputeJobStatus.PENDING.value)
            if analytics_type is not None:
                statement = statement.where(ComputeJobModel.analytics_type == analytics_type)
            statement = statement.order_by(ComputeJobModel.created_at_utc.asc()).limit(limit)
            rows = session.execute(statement).scalars().all()
            return [self._to_record(row) for row in rows]

    def mark_running(self, calculation_id: UUID) -> None:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            row.job_status = ComputeJobStatus.RUNNING.value
            row.attempt_count += 1
            row.error_message = None
            row.started_at_utc = row.started_at_utc or datetime.now(timezone.utc)
            row.completed_at_utc = None

    def mark_complete(self, calculation_id: UUID, *, response_payload: dict[str, Any]) -> None:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            now = datetime.now(timezone.utc)
            row.job_status = ComputeJobStatus.COMPLETE.value
            row.response_json = json.dumps(response_payload, sort_keys=True)
            row.error_message = None
            row.started_at_utc = row.started_at_utc or now
            row.completed_at_utc = now

    def mark_failed(self, calculation_id: UUID, *, error_message: str) -> None:
        with self._session() as session:
            row = self._get_model(session, calculation_id)
            now = datetime.now(timezone.utc)
            row.job_status = ComputeJobStatus.FAILED.value
            row.error_message = error_message
            row.started_at_utc = row.started_at_utc or now
            row.completed_at_utc = now

    def get_job(self, calculation_id: UUID) -> ComputeJobRecord | None:
        with self._session() as session:
            row = session.get(ComputeJobModel, str(calculation_id))
            return None if row is None else self._to_record(row)

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
            attempt_count=row.attempt_count,
            created_at_utc=_format_timestamp(row.created_at_utc) or "",
            started_at_utc=_format_timestamp(row.started_at_utc),
            completed_at_utc=_format_timestamp(row.completed_at_utc),
        )


settings = get_settings()
compute_job_store = ComputeJobStore(settings.LINEAGE_METADATA_DATABASE_URL)
