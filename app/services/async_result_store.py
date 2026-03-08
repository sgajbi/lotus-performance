from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings


class AsyncResultStatus(StrEnum):
    COMPLETE = "complete"
    FAILED = "failed"


class Base(DeclarativeBase):
    pass


class AsyncResultModel(Base):
    __tablename__ = "analytics_async_result"

    calculation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analytics_type: Mapped[str] = mapped_column(String(64), nullable=False)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class AsyncResultRecord:
    calculation_id: UUID
    analytics_type: str
    result_status: AsyncResultStatus
    response_payload: dict[str, Any] | None
    error_message: str | None
    error_type: str | None
    created_at_utc: str
    updated_at_utc: str


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class AsyncResultStore:
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
            session.query(AsyncResultModel).delete()

    def record_success(self, *, calculation_id: UUID, analytics_type: str, response_payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        with self._session() as session:
            session.merge(
                AsyncResultModel(
                    calculation_id=str(calculation_id),
                    analytics_type=analytics_type,
                    result_status=AsyncResultStatus.COMPLETE.value,
                    response_json=json.dumps(response_payload, sort_keys=True),
                    error_message=None,
                    error_type=None,
                    created_at_utc=now,
                    updated_at_utc=now,
                )
            )

    def record_failure(
        self,
        *,
        calculation_id: UUID,
        analytics_type: str,
        error_message: str,
        error_type: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._session() as session:
            existing = session.get(AsyncResultModel, str(calculation_id))
            created_at = existing.created_at_utc if existing is not None else now
            session.merge(
                AsyncResultModel(
                    calculation_id=str(calculation_id),
                    analytics_type=analytics_type,
                    result_status=AsyncResultStatus.FAILED.value,
                    response_json=None,
                    error_message=error_message,
                    error_type=error_type,
                    created_at_utc=created_at,
                    updated_at_utc=now,
                )
            )

    def get_result(self, calculation_id: UUID) -> AsyncResultRecord | None:
        with self._session() as session:
            row = session.get(AsyncResultModel, str(calculation_id))
            if row is None:
                return None
            return AsyncResultRecord(
                calculation_id=UUID(row.calculation_id),
                analytics_type=row.analytics_type,
                result_status=AsyncResultStatus(row.result_status),
                response_payload=json.loads(row.response_json) if row.response_json else None,
                error_message=row.error_message,
                error_type=row.error_type,
                created_at_utc=_format_timestamp(row.created_at_utc),
                updated_at_utc=_format_timestamp(row.updated_at_utc),
            )


settings = get_settings()
async_result_store = AsyncResultStore(settings.LINEAGE_METADATA_DATABASE_URL)
