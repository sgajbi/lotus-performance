from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterator
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text, case, create_engine, func, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings


class LineageStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class Base(DeclarativeBase):
    pass


class LineageRecordModel(Base):
    __tablename__ = "lineage_records"
    __table_args__ = (Index("ix_lineage_records_status", "status"),)

    calculation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    calculation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    artifact_names: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class LineagePayloadModel(Base):
    __tablename__ = "lineage_payloads"
    __table_args__ = (
        Index("ix_lineage_payloads_created_at", "created_at_utc"),
        Index("ix_lineage_payloads_lease_expires_at", "lease_expires_at_utc"),
    )

    calculation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    calculation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    leased_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass(frozen=True)
class LineageRecord:
    calculation_id: UUID
    calculation_type: str
    status: LineageStatus
    timestamp_utc: str
    artifact_names: list[str]
    error_message: str | None = None


@dataclass(frozen=True)
class LineagePayload:
    calculation_id: UUID
    calculation_type: str
    request_json: str
    response_json: str
    details: dict[str, str]
    attempt_count: int
    worker_id: str | None = None
    leased_at_utc: str | None = None
    lease_expires_at_utc: str | None = None


@dataclass(frozen=True)
class LineageQueueStats:
    pending_payload_count: int = 0
    leased_payload_count: int = 0
    retry_backlog_count: int = 0
    terminal_failure_count: int = 0
    oldest_pending_age_seconds: float = 0.0
    oldest_leased_age_seconds: float = 0.0


def _coerce_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _coerce_utc_datetime(value).isoformat().replace("+00:00", "Z")


class LineageMetadataStore:
    def __init__(self, database_url: str):
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._session_factory = sessionmaker(bind=self._engine, future=True)

    def create_schema(self) -> None:
        Base.metadata.create_all(self._engine)
        self._ensure_payload_lease_columns()

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

    def create_pending_record(self, calculation_id: UUID, calculation_type: str) -> None:
        now = datetime.now(timezone.utc)
        with self._session() as session:
            record = LineageRecordModel(
                calculation_id=str(calculation_id),
                calculation_type=calculation_type,
                status=LineageStatus.PENDING.value,
                timestamp_utc=now,
                artifact_names="",
                error_message=None,
            )
            session.merge(record)

    def mark_complete(self, calculation_id: UUID, artifact_names: list[str]) -> None:
        with self._session() as session:
            record = session.get(LineageRecordModel, str(calculation_id))
            if record is None:
                raise KeyError(f"Lineage record not found: {calculation_id}")
            record.status = LineageStatus.COMPLETE.value
            record.artifact_names = "\n".join(sorted(artifact_names))
            record.error_message = None

    def mark_failed(self, calculation_id: UUID, error_message: str) -> None:
        with self._session() as session:
            record = session.get(LineageRecordModel, str(calculation_id))
            if record is None:
                raise KeyError(f"Lineage record not found: {calculation_id}")
            record.status = LineageStatus.FAILED.value
            record.error_message = error_message
            payload = session.get(LineagePayloadModel, str(calculation_id))
            if payload is not None:
                payload.worker_id = None
                payload.leased_at_utc = None
                payload.lease_expires_at_utc = None

    def mark_pending(self, calculation_id: UUID) -> None:
        with self._session() as session:
            record = session.get(LineageRecordModel, str(calculation_id))
            if record is None:
                raise KeyError(f"Lineage record not found: {calculation_id}")
            record.status = LineageStatus.PENDING.value
            record.error_message = None
            payload = session.get(LineagePayloadModel, str(calculation_id))
            if payload is not None:
                payload.worker_id = None
                payload.leased_at_utc = None
                payload.lease_expires_at_utc = None

    def get_record(self, calculation_id: UUID) -> LineageRecord | None:
        with self._session() as session:
            statement = select(LineageRecordModel).where(LineageRecordModel.calculation_id == str(calculation_id))
            row = session.execute(statement).scalar_one_or_none()
            if row is None:
                return None
            return LineageRecord(
                calculation_id=UUID(row.calculation_id),
                calculation_type=row.calculation_type,
                status=LineageStatus(row.status),
                timestamp_utc=row.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                artifact_names=[name for name in row.artifact_names.splitlines() if name],
                error_message=row.error_message,
            )

    def clear_all_records(self) -> None:
        with self._session() as session:
            session.query(LineageRecordModel).delete()
            session.query(LineagePayloadModel).delete()

    def enqueue_lineage_payload(
        self,
        *,
        calculation_id: UUID,
        calculation_type: str,
        request_json: str,
        response_json: str,
        details: dict[str, str],
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._session() as session:
            record = LineageRecordModel(
                calculation_id=str(calculation_id),
                calculation_type=calculation_type,
                status=LineageStatus.PENDING.value,
                timestamp_utc=now,
                artifact_names="",
                error_message=None,
            )
            payload = LineagePayloadModel(
                calculation_id=str(calculation_id),
                calculation_type=calculation_type,
                request_json=request_json,
                response_json=response_json,
                details_json=json.dumps(details),
                created_at_utc=now,
                attempt_count=0,
                worker_id=None,
                leased_at_utc=None,
                lease_expires_at_utc=None,
            )
            session.merge(record)
            session.merge(payload)

    def list_pending_payloads(self, *, limit: int) -> list[LineagePayload]:
        with self._session() as session:
            statement = (
                select(LineagePayloadModel, LineageRecordModel)
                .join(LineageRecordModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
                .where(LineageRecordModel.status == LineageStatus.PENDING.value)
                .order_by(LineagePayloadModel.created_at_utc.asc())
                .limit(limit)
            )
            rows = session.execute(statement).all()
            return [
                LineagePayload(
                    calculation_id=UUID(payload.calculation_id),
                    calculation_type=payload.calculation_type,
                    request_json=payload.request_json,
                    response_json=payload.response_json,
                    details=json.loads(payload.details_json),
                    attempt_count=payload.attempt_count,
                    worker_id=payload.worker_id,
                    leased_at_utc=_format_timestamp(payload.leased_at_utc),
                    lease_expires_at_utc=_format_timestamp(payload.lease_expires_at_utc),
                )
                for payload, _ in rows
            ]

    def lease_pending_payloads(self, *, worker_id: str, limit: int, lease_seconds: int) -> list[LineagePayload]:
        now = datetime.now(timezone.utc)
        lease_expiry = now + timedelta(seconds=lease_seconds)
        with self._session() as session:
            statement = self._build_lease_pending_payloads_statement(
                now=now,
                limit=limit,
                dialect_name=session.bind.dialect.name if session.bind is not None else "",
            )
            rows = session.execute(statement).scalars().all()
            leased: list[LineagePayload] = []
            for row in rows:
                row.worker_id = worker_id
                row.leased_at_utc = now
                row.lease_expires_at_utc = lease_expiry
                row.attempt_count += 1
                leased.append(self._to_payload(row))
            return leased

    def increment_attempt_count(self, calculation_id: UUID) -> None:
        with self._session() as session:
            payload = session.get(LineagePayloadModel, str(calculation_id))
            if payload is None:
                raise KeyError(f"Lineage payload not found: {calculation_id}")
            payload.attempt_count += 1

    def get_payload(self, calculation_id: UUID) -> LineagePayload | None:
        with self._session() as session:
            payload = session.get(LineagePayloadModel, str(calculation_id))
            if payload is None:
                return None
            return LineagePayload(
                calculation_id=UUID(payload.calculation_id),
                calculation_type=payload.calculation_type,
                request_json=payload.request_json,
                response_json=payload.response_json,
                details=json.loads(payload.details_json),
                attempt_count=payload.attempt_count,
                worker_id=payload.worker_id,
                leased_at_utc=_format_timestamp(payload.leased_at_utc),
                lease_expires_at_utc=_format_timestamp(payload.lease_expires_at_utc),
            )

    def delete_payload(self, calculation_id: UUID) -> None:
        with self._session() as session:
            payload = session.get(LineagePayloadModel, str(calculation_id))
            if payload is not None:
                session.delete(payload)

    def get_pending_payload_stats(self, *, now: datetime | None = None) -> LineageQueueStats:
        stats_now = now or datetime.now(timezone.utc)
        with self._session() as session:
            aggregate_row = session.execute(
                select(
                    func.sum(
                        case((LineageRecordModel.status == LineageStatus.PENDING.value, 1), else_=0)
                    ).label("pending_payload_count"),
                    func.sum(
                        case(
                            (
                                (LineageRecordModel.status == LineageStatus.PENDING.value)
                                & (LineagePayloadModel.leased_at_utc.is_not(None))
                                & (
                                    LineagePayloadModel.lease_expires_at_utc.is_(None)
                                    | (LineagePayloadModel.lease_expires_at_utc >= stats_now)
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("leased_payload_count"),
                    func.sum(
                        case(
                            (
                                (LineageRecordModel.status == LineageStatus.PENDING.value)
                                & (LineagePayloadModel.attempt_count > 0),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("retry_backlog_count"),
                    func.sum(
                        case((LineageRecordModel.status == LineageStatus.FAILED.value, 1), else_=0)
                    ).label("terminal_failure_count"),
                    func.min(
                        case(
                            (LineageRecordModel.status == LineageStatus.PENDING.value, LineagePayloadModel.created_at_utc),
                            else_=None,
                        )
                    ).label("oldest_pending_created_at"),
                    func.min(
                        case(
                            (
                                (LineageRecordModel.status == LineageStatus.PENDING.value)
                                & (LineagePayloadModel.leased_at_utc.is_not(None))
                                & (
                                    LineagePayloadModel.lease_expires_at_utc.is_(None)
                                    | (LineagePayloadModel.lease_expires_at_utc >= stats_now)
                                ),
                                LineagePayloadModel.leased_at_utc,
                            ),
                            else_=None,
                        )
                    ).label("oldest_leased_at"),
                )
                .select_from(LineagePayloadModel)
                .join(LineageRecordModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            ).one()

            oldest_pending_age_seconds = 0.0
            if aggregate_row.oldest_pending_created_at is not None:
                oldest_pending_age_seconds = max(
                    0.0,
                    (stats_now - _coerce_utc_datetime(aggregate_row.oldest_pending_created_at)).total_seconds(),
                )
            oldest_leased_age_seconds = 0.0
            if aggregate_row.oldest_leased_at is not None:
                oldest_leased_age_seconds = max(
                    0.0,
                    (stats_now - _coerce_utc_datetime(aggregate_row.oldest_leased_at)).total_seconds(),
                )

            return LineageQueueStats(
                pending_payload_count=int(aggregate_row.pending_payload_count or 0),
                leased_payload_count=int(aggregate_row.leased_payload_count or 0),
                retry_backlog_count=int(aggregate_row.retry_backlog_count or 0),
                terminal_failure_count=int(aggregate_row.terminal_failure_count or 0),
                oldest_pending_age_seconds=oldest_pending_age_seconds,
                oldest_leased_age_seconds=oldest_leased_age_seconds,
            )

    def _build_lease_pending_payloads_statement(self, *, now: datetime, limit: int, dialect_name: str):
        statement = (
            select(LineagePayloadModel)
            .join(LineageRecordModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(
                (LineageRecordModel.status == LineageStatus.PENDING.value)
                & (
                    LineagePayloadModel.lease_expires_at_utc.is_(None)
                    | (LineagePayloadModel.lease_expires_at_utc < now)
                )
            )
            .order_by(LineagePayloadModel.created_at_utc.asc())
            .limit(limit)
        )
        if dialect_name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        return statement

    def _to_payload(self, payload: LineagePayloadModel) -> LineagePayload:
        return LineagePayload(
            calculation_id=UUID(payload.calculation_id),
            calculation_type=payload.calculation_type,
            request_json=payload.request_json,
            response_json=payload.response_json,
            details=json.loads(payload.details_json),
            attempt_count=payload.attempt_count,
            worker_id=payload.worker_id,
            leased_at_utc=_format_timestamp(payload.leased_at_utc),
            lease_expires_at_utc=_format_timestamp(payload.lease_expires_at_utc),
        )

    def _ensure_payload_lease_columns(self) -> None:
        inspector = inspect(self._engine)
        if "lineage_payloads" not in inspector.get_table_names():
            return

        existing_columns = {column["name"] for column in inspector.get_columns("lineage_payloads")}
        missing_columns = {
            "worker_id": "ALTER TABLE lineage_payloads ADD COLUMN worker_id VARCHAR(128)",
            "leased_at_utc": "ALTER TABLE lineage_payloads ADD COLUMN leased_at_utc DATETIME",
            "lease_expires_at_utc": "ALTER TABLE lineage_payloads ADD COLUMN lease_expires_at_utc DATETIME",
        }

        with self._engine.begin() as connection:
            for column_name, statement in missing_columns.items():
                if column_name not in existing_columns:
                    connection.execute(text(statement))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_lineage_payloads_lease_expires_at "
                    "ON lineage_payloads (lease_expires_at_utc)"
                )
            )


settings = get_settings()
lineage_metadata_store = LineageMetadataStore(settings.LINEAGE_METADATA_DATABASE_URL)
