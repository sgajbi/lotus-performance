from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterator
from uuid import UUID

from sqlalchemy import DateTime, String, Text, create_engine, select
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

    calculation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    calculation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    artifact_names: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


@dataclass(frozen=True)
class LineageRecord:
    calculation_id: UUID
    calculation_type: str
    status: LineageStatus
    timestamp_utc: str
    artifact_names: list[str]
    error_message: str | None = None


class LineageMetadataStore:
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


settings = get_settings()
lineage_metadata_store = LineageMetadataStore(settings.LINEAGE_METADATA_DATABASE_URL)
