from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import DateTime, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.services.durable_store_json import load_json_object_or_none
from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store
from app.services.durable_store_time import format_timestamp, normalize_filter_datetime

logger = logging.getLogger(__name__)

INVALID_ASYNC_RESULT_PAYLOAD_ERROR_TYPE = "InvalidAsyncResultPayload"
INVALID_ASYNC_RESULT_PAYLOAD_MESSAGE = "Stored async result response payload is invalid."


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


@dataclass(frozen=True)
class _AsyncResultRecordPayloadState:
    result_status: AsyncResultStatus
    response_payload: dict[str, Any] | None
    error_message: str | None
    error_type: str | None


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

    def prune_results_older_than(self, older_than: datetime, *, dry_run: bool = False) -> int:
        with self._session() as session:
            dialect_name = session.bind.dialect.name if session.bind is not None else ""
            cutoff = normalize_filter_datetime(older_than, dialect_name=dialect_name)
            statement = select(AsyncResultModel).where(AsyncResultModel.updated_at_utc <= cutoff)
            rows = session.execute(statement).scalars().all()
            if dry_run:
                return len(rows)
            for row in rows:
                session.delete(row)
            return len(rows)

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
            return _async_result_record_from_row(row)


def _load_response_payload(row: AsyncResultModel) -> dict[str, Any] | None:
    return load_json_object_or_none(
        row.response_json,
        logger=logger,
        payload_name="Async result response payload",
        identity_name="calculation_id",
        identity_value=row.calculation_id,
    )


def _async_result_record_payload_state(
    row: AsyncResultModel,
    *,
    response_payload: dict[str, Any] | None,
) -> _AsyncResultRecordPayloadState:
    result_status = AsyncResultStatus(row.result_status)
    error_message = row.error_message
    error_type = row.error_type
    if _has_invalid_response_payload(row, response_payload=response_payload):
        result_status = AsyncResultStatus.FAILED
        error_message = error_message or INVALID_ASYNC_RESULT_PAYLOAD_MESSAGE
        error_type = error_type or INVALID_ASYNC_RESULT_PAYLOAD_ERROR_TYPE
    return _AsyncResultRecordPayloadState(
        result_status=result_status,
        response_payload=response_payload,
        error_message=error_message,
        error_type=error_type,
    )


def _has_invalid_response_payload(
    row: AsyncResultModel,
    *,
    response_payload: dict[str, Any] | None,
) -> bool:
    return bool(row.response_json) and response_payload is None


def _async_result_record_from_row(row: AsyncResultModel) -> AsyncResultRecord:
    payload_state = _async_result_record_payload_state(row, response_payload=_load_response_payload(row))
    return AsyncResultRecord(
        calculation_id=UUID(row.calculation_id),
        analytics_type=row.analytics_type,
        result_status=payload_state.result_status,
        response_payload=payload_state.response_payload,
        error_message=payload_state.error_message,
        error_type=payload_state.error_type,
        created_at_utc=format_timestamp(row.created_at_utc) or "",
        updated_at_utc=format_timestamp(row.updated_at_utc) or "",
    )


_store_cache: dict[str, AsyncResultStore] = {}


def get_async_result_store(*, database_url: str | None = None) -> AsyncResultStore:
    return resolve_runtime_store(cache=_store_cache, factory=AsyncResultStore, database_url=database_url)


async_result_store = RuntimeStoreProxy(get_async_result_store)
