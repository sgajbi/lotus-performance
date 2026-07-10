from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable, Iterator, Mapping, cast
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    case,
    delete,
    exists,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.services.calculation_id_filtering import apply_calculation_id_prefix_filter
from app.services.durable_database_engine import create_durable_database_engine
from app.services.durable_store_inspection import (
    INSPECTION_STATUS_ACTIVE,
    INSPECTION_STATUS_ALL,
    INSPECTION_STATUS_FAILED,
    INSPECTION_STATUS_RECLAIMABLE,
    apply_min_age_filter,
    build_inspection_query_context,
)
from app.services.durable_store_json import load_json_object_or_none
from app.services.durable_store_pagination import next_offset_or_none, recovery_cursor_or_none
from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store
from app.services.durable_store_time import (
    coerce_utc_datetime,
    elapsed_seconds_since,
    elapsed_seconds_since_or_zero,
    format_timestamp,
    normalize_filter_datetime,
)

logger = logging.getLogger(__name__)

INVALID_LINEAGE_PAYLOAD_DETAILS_MESSAGE = "Stored lineage payload details are invalid."


class LineagePayloadLeaseOwnershipError(ValueError):
    """Raised when a worker tries to finalize a lineage payload it no longer owns."""


class LineageStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


LINEAGE_TERMINAL_STATUSES = (
    LineageStatus.COMPLETE.value,
    LineageStatus.FAILED.value,
)


class Base(DeclarativeBase):
    pass


class LineageRecordModel(Base):
    __tablename__ = "lineage_records"
    __table_args__ = (
        Index("ix_lineage_records_status", "status"),
        Index("ix_lineage_records_terminal_retention", "status", "timestamp_utc", "calculation_id"),
        Index(
            "ix_lineage_records_status_type_timestamp",
            "status",
            "calculation_type",
            "timestamp_utc",
            "calculation_id",
        ),
        Index("ix_lineage_records_type_timestamp", "calculation_type", "timestamp_utc", "calculation_id"),
    )

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
        Index("ix_lineage_payloads_calculation_created_at", "calculation_id", "created_at_utc"),
        Index(
            "ix_lineage_payloads_lease_expires_created_at",
            "lease_expires_at_utc",
            "created_at_utc",
            "calculation_id",
        ),
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
    reclaimable_count: int = 0


@dataclass(frozen=True)
class LineageQueueInspectionAnchors:
    oldest_pending_calculation_id: str | None = None
    oldest_leased_calculation_id: str | None = None
    latest_terminal_failure_calculation_id: str | None = None
    latest_recovered_calculation_id: str | None = None


@dataclass(frozen=True)
class LineageQueueInspectionItem:
    calculation_id: str
    calculation_type: str
    status: str
    active_since_utc: str | None
    age_seconds: float | None
    attempt_count: int
    error_message: str | None


@dataclass(frozen=True)
class LineageQueueInspectionTiming:
    status: str
    active_since: datetime | None


@dataclass(frozen=True)
class LineageQueueInspectionPage:
    total_count: int
    next_offset: int | None
    items: list[LineageQueueInspectionItem]


@dataclass(frozen=True)
class LineageRecoveryEvent:
    calculation_id: str
    calculation_type: str
    recovery_kind: str
    recovered_at_utc: str
    attempt_count: int


@dataclass(frozen=True)
class LineageRecoveryEventPage:
    total_count: int
    next_offset: int | None
    next_cursor_recovered_before: str | None
    next_cursor_calculation_id_before: str | None
    items: list[LineageRecoveryEvent]


@dataclass(frozen=True)
class _LineageRecoveryTimeFilters:
    recovered_after: datetime | None
    recovered_before: datetime | None
    cursor_recovered_before: datetime | None


class LineageMetadataStore:
    def __init__(self, database_url: str):
        self._engine = create_durable_database_engine(database_url)
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

    def mark_complete(
        self,
        calculation_id: UUID,
        artifact_names: list[str],
        *,
        timestamp_utc: datetime | None = None,
        worker_id: str | None = None,
    ) -> None:
        with self._session() as session:
            record = session.get(LineageRecordModel, str(calculation_id))
            if record is None:
                raise KeyError(f"Lineage record not found: {calculation_id}")
            payload = session.get(LineagePayloadModel, str(calculation_id))
            _ensure_lineage_payload_active_lease_owner(
                payload,
                calculation_id=calculation_id,
                worker_id=worker_id,
                transition="mark complete",
                now=datetime.now(timezone.utc),
            )
            record.timestamp_utc = timestamp_utc or datetime.now(timezone.utc)
            record.status = LineageStatus.COMPLETE.value
            record.artifact_names = "\n".join(sorted(artifact_names))
            record.error_message = None

    def mark_failed(self, calculation_id: UUID, error_message: str) -> None:
        with self._session() as session:
            record = session.get(LineageRecordModel, str(calculation_id))
            if record is None:
                raise KeyError(f"Lineage record not found: {calculation_id}")
            record.timestamp_utc = datetime.now(timezone.utc)
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
            record.timestamp_utc = datetime.now(timezone.utc)
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
                timestamp_utc=format_timestamp(row.timestamp_utc) or "",
                artifact_names=[name for name in row.artifact_names.splitlines() if name],
                error_message=row.error_message,
            )

    def clear_all_records(self) -> None:
        with self._session() as session:
            session.query(LineageRecordModel).delete()
            session.query(LineagePayloadModel).delete()

    def list_terminal_calculation_ids_older_than(self, older_than: datetime) -> list[str]:
        with self._session() as session:
            cutoff = normalize_filter_datetime(
                older_than,
                dialect_name=session.bind.dialect.name if session.bind is not None else "",
            )
            statement = (
                select(LineageRecordModel.calculation_id)
                .where(LineageRecordModel.status.in_(LINEAGE_TERMINAL_STATUSES))
                .where(LineageRecordModel.timestamp_utc <= cutoff)
                .order_by(LineageRecordModel.timestamp_utc.asc(), LineageRecordModel.calculation_id.asc())
            )
            return [row[0] for row in session.execute(statement).all()]

    def delete_calculation_ids(self, calculation_ids: list[str]) -> int:
        if not calculation_ids:
            return 0
        with self._session() as session:
            session.execute(delete(LineagePayloadModel).where(LineagePayloadModel.calculation_id.in_(calculation_ids)))
            result = session.execute(
                delete(LineageRecordModel).where(LineageRecordModel.calculation_id.in_(calculation_ids))
            )
            return int(result.rowcount or 0)

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
            pending: list[LineagePayload] = []
            for payload, _ in rows:
                details = _load_payload_details(payload.details_json, calculation_id=payload.calculation_id)
                if details is None:
                    _mark_invalid_payload_details(session, payload.calculation_id, now=datetime.now(timezone.utc))
                    continue
                pending.append(self._to_payload(payload, details=details))
            return pending

    def lease_pending_payloads(self, *, worker_id: str, limit: int, lease_seconds: int) -> list[LineagePayload]:
        now = datetime.now(timezone.utc)
        lease_expiry = now + timedelta(seconds=lease_seconds)
        with self._session() as session:
            dialect_name = session.bind.dialect.name if session.bind is not None else ""
            if dialect_name == "postgresql":
                return self._lease_pending_payloads_postgresql(
                    session=session,
                    now=now,
                    lease_expiry=lease_expiry,
                    worker_id=worker_id,
                    limit=limit,
                )
            statement = self._build_lease_pending_payloads_statement(
                now=now,
                limit=limit,
                dialect_name=dialect_name,
            )
            rows = session.execute(statement).scalars().all()
            leased: list[LineagePayload] = []
            for row in rows:
                details = _load_payload_details(row.details_json, calculation_id=row.calculation_id)
                if details is None:
                    _mark_invalid_payload_details(session, row.calculation_id, now=now)
                    continue
                row.worker_id = worker_id
                row.leased_at_utc = now
                row.lease_expires_at_utc = lease_expiry
                row.attempt_count += 1
                leased.append(self._to_payload(row, details=details))
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
            details = _load_payload_details(payload.details_json, calculation_id=payload.calculation_id)
            if details is None:
                _mark_invalid_payload_details(session, payload.calculation_id, now=datetime.now(timezone.utc))
                return None
            return self._to_payload(payload, details=details)

    def ensure_active_payload_lease_owner(self, calculation_id: UUID, *, worker_id: str | None) -> None:
        with self._session() as session:
            payload = session.get(LineagePayloadModel, str(calculation_id))
            _ensure_lineage_payload_active_lease_owner(
                payload,
                calculation_id=calculation_id,
                worker_id=worker_id,
                transition="materialize",
                now=datetime.now(timezone.utc),
            )

    def delete_payload(self, calculation_id: UUID, *, worker_id: str | None = None) -> None:
        with self._session() as session:
            payload = session.get(LineagePayloadModel, str(calculation_id))
            if payload is not None:
                _ensure_lineage_payload_active_lease_owner(
                    payload,
                    calculation_id=calculation_id,
                    worker_id=worker_id,
                    transition="delete",
                    now=datetime.now(timezone.utc),
                )
                session.delete(payload)

    def get_pending_payload_stats(self, *, now: datetime | None = None) -> LineageQueueStats:
        stats_now = now or datetime.now(timezone.utc)
        with self._session() as session:
            aggregate_row = session.execute(self._build_pending_payload_stats_statement(now=stats_now)).one()

            return _lineage_queue_stats_from_aggregate_row(aggregate_row=aggregate_row, stats_now=stats_now)

    def get_queue_inspection_anchors(self, *, now: datetime | None = None) -> LineageQueueInspectionAnchors:
        with self._session() as session:
            row = session.execute(
                self._build_queue_inspection_anchors_statement(now=now or datetime.now(timezone.utc))
            ).one()
            return LineageQueueInspectionAnchors(
                oldest_pending_calculation_id=row.oldest_pending_calculation_id,
                oldest_leased_calculation_id=row.oldest_leased_calculation_id,
                latest_terminal_failure_calculation_id=row.latest_terminal_failure_calculation_id,
                latest_recovered_calculation_id=row.latest_recovered_calculation_id,
            )

    def list_recent_recoveries(
        self,
        *,
        limit: int = 5,
        offset: int = 0,
        calculation_type: str | None = None,
        calculation_id_contains: str | None = None,
        recovered_after: datetime | None = None,
        recovered_before: datetime | None = None,
        cursor_recovered_before: datetime | None = None,
        cursor_calculation_id_before: str | None = None,
    ) -> LineageRecoveryEventPage:
        with self._session() as session:
            dialect_name = session.bind.dialect.name if session.bind is not None else ""
            recovery_time_filters = _normalize_lineage_recovery_time_filters(
                recovered_after=recovered_after,
                recovered_before=recovered_before,
                cursor_recovered_before=cursor_recovered_before,
                dialect_name=dialect_name,
            )
            rows = session.execute(
                self._build_recent_recoveries_statement(
                    limit=limit,
                    offset=offset,
                    calculation_type=calculation_type,
                    calculation_id_contains=calculation_id_contains,
                    recovered_after=recovery_time_filters.recovered_after,
                    recovered_before=recovery_time_filters.recovered_before,
                    cursor_recovered_before=recovery_time_filters.cursor_recovered_before,
                    cursor_calculation_id_before=cursor_calculation_id_before,
                )
            ).all()
            events = self._recovery_events_from_rows(
                cast(Iterable[tuple[LineageRecordModel, LineagePayloadModel]], rows)
            )
            total_count = int(
                session.execute(
                    self._build_recent_recoveries_count_statement(
                        calculation_type=calculation_type,
                        calculation_id_contains=calculation_id_contains,
                        recovered_after=recovery_time_filters.recovered_after,
                        recovered_before=recovery_time_filters.recovered_before,
                        cursor_recovered_before=recovery_time_filters.cursor_recovered_before,
                        cursor_calculation_id_before=cursor_calculation_id_before,
                    )
                ).scalar_one()
                or 0
            )
            return _lineage_recovery_event_page(offset=offset, events=events, total_count=total_count)

    def list_inspection_items(
        self,
        *,
        status_filter: str,
        limit: int,
        offset: int = 0,
        min_age_seconds: float = 0.0,
        calculation_type: str | None = None,
        calculation_id_contains: str | None = None,
        now: datetime | None = None,
    ) -> LineageQueueInspectionPage:
        inspection_context = build_inspection_query_context(
            status_filter=status_filter,
            min_age_seconds=min_age_seconds,
            now=now,
        )

        with self._session() as session:
            count_statement, statement = self._build_inspection_query_statements(
                status_filter=inspection_context.status_filter,
                now=inspection_context.now,
                limit=limit,
                offset=offset,
                calculation_type=calculation_type,
                calculation_id_contains=calculation_id_contains,
                min_age_threshold=inspection_context.min_age_threshold,
            )
            rows = session.execute(statement).all()
            items = [self._to_inspection_item(record, payload, now=inspection_context.now) for record, payload in rows]
            total_count = int(session.execute(count_statement).scalar_one() or 0)
            next_offset = next_offset_or_none(offset=offset, item_count=len(items), total_count=total_count)
            return LineageQueueInspectionPage(total_count=total_count, next_offset=next_offset, items=items)

    def _build_inspection_query_statements(
        self,
        *,
        status_filter: str,
        now: datetime,
        limit: int,
        offset: int,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        count_builder, items_builder = self._inspection_statement_builders(status_filter)
        filter_kwargs = {
            "now": now,
            "calculation_type": calculation_type,
            "calculation_id_contains": calculation_id_contains,
            "min_age_threshold": min_age_threshold,
        }
        return (
            count_builder(**filter_kwargs),
            items_builder(limit=limit, offset=offset, **filter_kwargs),
        )

    def _inspection_statement_builders(self, status_filter: str):
        builders = {
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
            INSPECTION_STATUS_RECLAIMABLE: (
                self._build_reclaimable_inspection_count_statement,
                self._build_reclaimable_inspection_items_statement,
            ),
        }
        try:
            return builders[status_filter]
        except KeyError:
            raise ValueError(f"Unsupported status filter: {status_filter}") from None

    def _build_pending_payload_stats_statement(self, *, now: datetime):
        pending_payload_filter = _pending_lineage_payload_filter()
        active_lease_filter = _active_pending_payload_lease_filter(now)
        retry_backlog_filter = _retry_pending_payload_filter()
        reclaimable_filter = _reclaimable_pending_payload_filter(now)
        return (
            select(
                func.sum(case((pending_payload_filter, 1), else_=0)).label("pending_payload_count"),
                func.sum(case((active_lease_filter, 1), else_=0)).label("leased_payload_count"),
                func.sum(case((retry_backlog_filter, 1), else_=0)).label("retry_backlog_count"),
                func.sum(case((reclaimable_filter, 1), else_=0)).label("reclaimable_count"),
                func.sum(case((LineageRecordModel.status == LineageStatus.FAILED.value, 1), else_=0)).label(
                    "terminal_failure_count"
                ),
                func.min(case((pending_payload_filter, LineagePayloadModel.created_at_utc))).label(
                    "oldest_pending_created_at"
                ),
                func.min(case((active_lease_filter, LineagePayloadModel.leased_at_utc))).label("oldest_leased_at"),
            )
            .select_from(LineagePayloadModel)
            .join(LineageRecordModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
        )

    def _build_queue_inspection_anchors_statement(self, *, now: datetime):
        pending_lookup = (
            select(LineagePayloadModel.calculation_id)
            .join(LineageRecordModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(LineageRecordModel.status == LineageStatus.PENDING.value)
            .order_by(LineagePayloadModel.created_at_utc.asc())
            .limit(1)
            .scalar_subquery()
        )
        leased_lookup = (
            select(LineagePayloadModel.calculation_id)
            .join(LineageRecordModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(_active_pending_payload_lease_filter(now))
            .order_by(LineagePayloadModel.leased_at_utc.asc(), LineagePayloadModel.created_at_utc.asc())
            .limit(1)
            .scalar_subquery()
        )
        failed_lookup = (
            select(LineageRecordModel.calculation_id)
            .where(LineageRecordModel.status == LineageStatus.FAILED.value)
            .order_by(LineageRecordModel.timestamp_utc.desc())
            .limit(1)
            .scalar_subquery()
        )
        return select(
            pending_lookup.label("oldest_pending_calculation_id"),
            leased_lookup.label("oldest_leased_calculation_id"),
            failed_lookup.label("latest_terminal_failure_calculation_id"),
            (
                select(LineageRecordModel.calculation_id)
                .join(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
                .where(_retry_pending_payload_filter())
                .order_by(LineageRecordModel.timestamp_utc.desc())
                .limit(1)
                .scalar_subquery()
            ).label("latest_recovered_calculation_id"),
        )

    def _build_recent_recoveries_statement(
        self,
        *,
        limit: int,
        offset: int,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        recovered_after: datetime | None,
        recovered_before: datetime | None,
        cursor_recovered_before: datetime | None,
        cursor_calculation_id_before: str | None,
    ):
        statement = (
            select(LineageRecordModel, LineagePayloadModel)
            .join(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(_retry_pending_payload_filter())
            .order_by(LineageRecordModel.timestamp_utc.desc(), LineageRecordModel.calculation_id.desc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_recovery_time_filters(
            self._apply_calculation_filters(
                statement,
                calculation_type=calculation_type,
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
        calculation_type: str | None,
        calculation_id_contains: str | None,
        recovered_after: datetime | None,
        recovered_before: datetime | None,
        cursor_recovered_before: datetime | None,
        cursor_calculation_id_before: str | None,
    ):
        statement = (
            select(func.count())
            .select_from(LineageRecordModel)
            .join(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(_retry_pending_payload_filter())
        )
        return self._apply_recovery_time_filters(
            self._apply_calculation_filters(
                statement,
                calculation_type=calculation_type,
                calculation_id_contains=calculation_id_contains,
            ),
            recovered_after=recovered_after,
            recovered_before=recovered_before,
            cursor_recovered_before=cursor_recovered_before,
            cursor_calculation_id_before=cursor_calculation_id_before,
        )

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
            statement = statement.where(LineageRecordModel.timestamp_utc >= recovered_after)
        if recovered_before is not None:
            statement = statement.where(LineageRecordModel.timestamp_utc <= recovered_before)
        if cursor_recovered_before is not None:
            cursor_filter = LineageRecordModel.timestamp_utc < cursor_recovered_before
            if cursor_calculation_id_before:
                cursor_filter = cursor_filter | (
                    (LineageRecordModel.timestamp_utc == cursor_recovered_before)
                    & (LineageRecordModel.calculation_id < cursor_calculation_id_before)
                )
            statement = statement.where(cursor_filter)
        return statement

    def _apply_calculation_filters(
        self, statement, *, calculation_type: str | None, calculation_id_contains: str | None
    ):
        if calculation_type is not None:
            statement = statement.where(LineageRecordModel.calculation_type == calculation_type)
        return apply_calculation_id_prefix_filter(statement, LineageRecordModel.calculation_id, calculation_id_contains)

    @staticmethod
    def _build_active_since_expression(*, now: datetime):
        return case(
            (LineageRecordModel.status == LineageStatus.FAILED.value, LineageRecordModel.timestamp_utc),
            (
                (LineagePayloadModel.leased_at_utc.is_not(None))
                & (
                    LineagePayloadModel.lease_expires_at_utc.is_(None)
                    | (LineagePayloadModel.lease_expires_at_utc >= now)
                ),
                LineagePayloadModel.leased_at_utc,
            ),
            else_=LineagePayloadModel.created_at_utc,
        )

    def _apply_min_age_filter(self, statement, *, now: datetime, min_age_threshold: datetime | None):
        return apply_min_age_filter(
            statement,
            active_since=self._build_active_since_expression(now=now),
            min_age_threshold=min_age_threshold,
        )

    def _build_active_inspection_count_statement(
        self,
        *,
        now: datetime,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(func.count())
            .select_from(LineageRecordModel)
            .join(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(LineageRecordModel.status == LineageStatus.PENDING.value)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, now=now, min_age_threshold=min_age_threshold),
            calculation_type=calculation_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_failed_inspection_count_statement(
        self,
        *,
        now: datetime,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(func.count())
            .select_from(LineageRecordModel)
            .outerjoin(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(LineageRecordModel.status == LineageStatus.FAILED.value)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, now=now, min_age_threshold=min_age_threshold),
            calculation_type=calculation_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_all_inspection_count_statement(
        self,
        *,
        now: datetime,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(func.count())
            .select_from(LineageRecordModel)
            .outerjoin(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, now=now, min_age_threshold=min_age_threshold),
            calculation_type=calculation_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_reclaimable_inspection_count_statement(
        self,
        *,
        now: datetime,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(func.count())
            .select_from(LineageRecordModel)
            .join(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(
                (LineageRecordModel.status == LineageStatus.PENDING.value)
                & LineagePayloadModel.lease_expires_at_utc.is_not(None)
                & (LineagePayloadModel.lease_expires_at_utc < now)
            )
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, now=now, min_age_threshold=min_age_threshold),
            calculation_type=calculation_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_active_inspection_items_statement(
        self,
        *,
        now: datetime,
        limit: int,
        offset: int,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        active_since = self._build_active_since_expression(now=now)
        statement = (
            select(LineageRecordModel, LineagePayloadModel)
            .join(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(LineageRecordModel.status == LineageStatus.PENDING.value)
            .order_by(active_since.asc(), LineagePayloadModel.created_at_utc.asc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, now=now, min_age_threshold=min_age_threshold),
            calculation_type=calculation_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_failed_inspection_items_statement(
        self,
        *,
        now: datetime,
        limit: int,
        offset: int,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(LineageRecordModel, LineagePayloadModel)
            .outerjoin(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(LineageRecordModel.status == LineageStatus.FAILED.value)
            .order_by(LineageRecordModel.timestamp_utc.desc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, now=now, min_age_threshold=min_age_threshold),
            calculation_type=calculation_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_all_inspection_items_statement(
        self,
        *,
        now: datetime,
        limit: int,
        offset: int,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        active_since = self._build_active_since_expression(now=now)
        statement = (
            select(LineageRecordModel, LineagePayloadModel)
            .outerjoin(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .order_by(active_since.asc().nullslast(), LineageRecordModel.timestamp_utc.asc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, now=now, min_age_threshold=min_age_threshold),
            calculation_type=calculation_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_reclaimable_inspection_items_statement(
        self,
        *,
        now: datetime,
        limit: int,
        offset: int,
        calculation_type: str | None,
        calculation_id_contains: str | None,
        min_age_threshold: datetime | None,
    ):
        statement = (
            select(LineageRecordModel, LineagePayloadModel)
            .join(LineagePayloadModel, LineagePayloadModel.calculation_id == LineageRecordModel.calculation_id)
            .where(
                (LineageRecordModel.status == LineageStatus.PENDING.value)
                & LineagePayloadModel.lease_expires_at_utc.is_not(None)
                & (LineagePayloadModel.lease_expires_at_utc < now)
            )
            .order_by(LineagePayloadModel.lease_expires_at_utc.asc(), LineagePayloadModel.created_at_utc.asc())
            .offset(offset)
            .limit(limit)
        )
        return self._apply_calculation_filters(
            self._apply_min_age_filter(statement, now=now, min_age_threshold=min_age_threshold),
            calculation_type=calculation_type,
            calculation_id_contains=calculation_id_contains,
        )

    def _build_lease_pending_payloads_statement(self, *, now: datetime, limit: int, dialect_name: str):
        pending_record_exists = exists(
            select(1).where(
                (LineageRecordModel.calculation_id == LineagePayloadModel.calculation_id)
                & (LineageRecordModel.status == LineageStatus.PENDING.value)
            )
        )
        statement = (
            select(LineagePayloadModel)
            .where(
                pending_record_exists
                & (
                    LineagePayloadModel.lease_expires_at_utc.is_(None)
                    | (LineagePayloadModel.lease_expires_at_utc < now)
                )
            )
            .order_by(LineagePayloadModel.created_at_utc.asc(), LineagePayloadModel.calculation_id.asc())
            .limit(limit)
        )
        if dialect_name == "postgresql":
            statement = statement.with_for_update(of=LineagePayloadModel, skip_locked=True)
        return statement

    def _lease_pending_payloads_postgresql(
        self,
        *,
        session: Session,
        now: datetime,
        lease_expiry: datetime,
        worker_id: str,
        limit: int,
    ) -> list[LineagePayload]:
        rows = session.execute(
            _postgresql_pending_payload_lease_statement(),
            _postgresql_pending_payload_lease_params(
                worker_id=worker_id,
                leased_at_utc=now,
                lease_expires_at_utc=lease_expiry,
                limit=limit,
            ),
        ).mappings()
        leased: list[LineagePayload] = []
        for row in rows:
            calculation_id, payload = _postgresql_pending_payload_from_row(row)
            if payload is None:
                _mark_invalid_payload_details(session, calculation_id, now=now)
                continue
            leased.append(payload)
        return leased

    def _to_payload(self, payload: LineagePayloadModel, *, details: dict[str, str] | None = None) -> LineagePayload:
        loaded_details = (
            details
            if details is not None
            else _load_payload_details(payload.details_json, calculation_id=payload.calculation_id)
        )
        return LineagePayload(
            calculation_id=UUID(payload.calculation_id),
            calculation_type=payload.calculation_type,
            request_json=payload.request_json,
            response_json=payload.response_json,
            details={} if loaded_details is None else loaded_details,
            attempt_count=payload.attempt_count,
            worker_id=payload.worker_id,
            leased_at_utc=format_timestamp(payload.leased_at_utc),
            lease_expires_at_utc=format_timestamp(payload.lease_expires_at_utc),
        )

    def _to_recovery_event(
        self,
        *,
        record: LineageRecordModel,
        payload: LineagePayloadModel,
    ) -> LineageRecoveryEvent | None:
        recovered_at_utc = format_timestamp(record.timestamp_utc)
        if recovered_at_utc is None:
            return None
        return LineageRecoveryEvent(
            calculation_id=record.calculation_id,
            calculation_type=record.calculation_type,
            recovery_kind="retryable_materialization_failure",
            recovered_at_utc=recovered_at_utc,
            attempt_count=payload.attempt_count,
        )

    def _recovery_events_from_rows(
        self,
        rows: Iterable[tuple[LineageRecordModel, LineagePayloadModel]],
    ) -> list[LineageRecoveryEvent]:
        events: list[LineageRecoveryEvent] = []
        for record, payload in rows:
            event = self._to_recovery_event(record=record, payload=payload)
            if event is None:
                continue
            events.append(event)
        return events

    def _to_inspection_item(
        self,
        record: LineageRecordModel,
        payload: LineagePayloadModel | None,
        *,
        now: datetime,
    ) -> LineageQueueInspectionItem:
        timing = self._inspection_timing(record=record, payload=payload, now=now)

        age_seconds = None
        if timing.active_since is not None:
            age_seconds = elapsed_seconds_since(now, timing.active_since)

        return LineageQueueInspectionItem(
            calculation_id=record.calculation_id,
            calculation_type=record.calculation_type,
            status=timing.status,
            active_since_utc=format_timestamp(timing.active_since),
            age_seconds=age_seconds,
            attempt_count=0 if payload is None else payload.attempt_count,
            error_message=record.error_message,
        )

    @staticmethod
    def _inspection_timing(
        *,
        record: LineageRecordModel,
        payload: LineagePayloadModel | None,
        now: datetime,
    ) -> LineageQueueInspectionTiming:
        if record.status == LineageStatus.FAILED.value:
            return LineageQueueInspectionTiming(
                status=LineageStatus.FAILED.value,
                active_since=record.timestamp_utc,
            )

        if payload is None:
            return LineageQueueInspectionTiming(
                status=LineageStatus.PENDING.value,
                active_since=record.timestamp_utc,
            )

        if record.status == LineageStatus.PENDING.value and _payload_has_active_lease(payload, now=now):
            return LineageQueueInspectionTiming(status="leased", active_since=payload.leased_at_utc)

        return LineageQueueInspectionTiming(
            status=LineageStatus.PENDING.value,
            active_since=payload.created_at_utc,
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
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_lineage_payloads_created_at ON lineage_payloads (created_at_utc)")
            )
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_lineage_records_status ON lineage_records (status)"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_lineage_records_terminal_retention "
                    "ON lineage_records (status, timestamp_utc, calculation_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_lineage_records_status_type_timestamp "
                    "ON lineage_records (status, calculation_type, timestamp_utc, calculation_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_lineage_records_type_timestamp "
                    "ON lineage_records (calculation_type, timestamp_utc, calculation_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_lineage_payloads_calculation_created_at "
                    "ON lineage_payloads (calculation_id, created_at_utc)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_lineage_payloads_lease_expires_created_at "
                    "ON lineage_payloads (lease_expires_at_utc, created_at_utc, calculation_id)"
                )
            )


_store_cache: dict[str, LineageMetadataStore] = {}


def get_lineage_metadata_store(*, database_url: str | None = None) -> LineageMetadataStore:
    return resolve_runtime_store(cache=_store_cache, factory=LineageMetadataStore, database_url=database_url)


lineage_metadata_store = RuntimeStoreProxy(get_lineage_metadata_store)


def _normalize_lineage_recovery_time_filters(
    *,
    recovered_after: datetime | None,
    recovered_before: datetime | None,
    cursor_recovered_before: datetime | None,
    dialect_name: str,
) -> _LineageRecoveryTimeFilters:
    return _LineageRecoveryTimeFilters(
        recovered_after=normalize_filter_datetime(recovered_after, dialect_name=dialect_name),
        recovered_before=normalize_filter_datetime(recovered_before, dialect_name=dialect_name),
        cursor_recovered_before=normalize_filter_datetime(cursor_recovered_before, dialect_name=dialect_name),
    )


def _lineage_recovery_event_page(
    *,
    offset: int,
    events: list[LineageRecoveryEvent],
    total_count: int,
) -> LineageRecoveryEventPage:
    next_offset = next_offset_or_none(offset=offset, item_count=len(events), total_count=total_count)
    cursor = recovery_cursor_or_none(next_offset=next_offset, items=events)
    return LineageRecoveryEventPage(
        total_count=total_count,
        next_offset=next_offset,
        next_cursor_recovered_before=cursor.recovered_before,
        next_cursor_calculation_id_before=cursor.calculation_id_before,
        items=events,
    )


def _payload_has_active_lease(payload: LineagePayloadModel, *, now: datetime) -> bool:
    if payload.leased_at_utc is None:
        return False
    lease_expires_at = payload.lease_expires_at_utc
    normalized_lease_expires_at = None if lease_expires_at is None else coerce_utc_datetime(lease_expires_at)
    return normalized_lease_expires_at is None or normalized_lease_expires_at >= now


def _ensure_lineage_payload_active_lease_owner(
    payload: LineagePayloadModel | None,
    *,
    calculation_id: UUID,
    worker_id: str | None,
    transition: str,
    now: datetime,
) -> None:
    if worker_id is None:
        return
    if payload is None:
        raise LineagePayloadLeaseOwnershipError(
            f"Cannot {transition} lineage payload without an active lease: {calculation_id}"
        )
    if payload.worker_id != worker_id:
        raise LineagePayloadLeaseOwnershipError(
            f"Lineage payload lease owner mismatch while trying to {transition}: {calculation_id}"
        )
    if not _payload_has_active_lease(payload, now=now):
        raise LineagePayloadLeaseOwnershipError(
            f"Cannot {transition} lineage payload after lease expiry: {calculation_id}"
        )


def _pending_lineage_payload_filter():
    return LineageRecordModel.status == LineageStatus.PENDING.value


def _payload_lease_active_filter(now: datetime):
    return LineagePayloadModel.lease_expires_at_utc.is_(None) | (LineagePayloadModel.lease_expires_at_utc >= now)


def _active_pending_payload_lease_filter(now: datetime):
    return (
        _pending_lineage_payload_filter()
        & LineagePayloadModel.leased_at_utc.is_not(None)
        & _payload_lease_active_filter(now)
    )


def _retry_pending_payload_filter():
    return _pending_lineage_payload_filter() & (LineagePayloadModel.attempt_count > 0)


def _reclaimable_pending_payload_filter(now: datetime):
    return (
        _pending_lineage_payload_filter()
        & LineagePayloadModel.lease_expires_at_utc.is_not(None)
        & (LineagePayloadModel.lease_expires_at_utc < now)
    )


def _lineage_queue_stats_from_aggregate_row(*, aggregate_row: object, stats_now: datetime) -> LineageQueueStats:
    return LineageQueueStats(
        pending_payload_count=_aggregate_int(aggregate_row, "pending_payload_count"),
        leased_payload_count=_aggregate_int(aggregate_row, "leased_payload_count"),
        retry_backlog_count=_aggregate_int(aggregate_row, "retry_backlog_count"),
        terminal_failure_count=_aggregate_int(aggregate_row, "terminal_failure_count"),
        oldest_pending_age_seconds=elapsed_seconds_since_or_zero(
            stats_now,
            getattr(aggregate_row, "oldest_pending_created_at"),
        ),
        oldest_leased_age_seconds=elapsed_seconds_since_or_zero(stats_now, getattr(aggregate_row, "oldest_leased_at")),
        reclaimable_count=_aggregate_int(aggregate_row, "reclaimable_count"),
    )


def _aggregate_int(aggregate_row: object, field_name: str) -> int:
    return int(getattr(aggregate_row, field_name) or 0)


def _postgresql_pending_payload_lease_statement():
    return text(
        """
        UPDATE lineage_payloads AS payload
        SET worker_id = :worker_id,
            leased_at_utc = :leased_at_utc,
            lease_expires_at_utc = :lease_expires_at_utc,
            attempt_count = payload.attempt_count + 1
        FROM (
            SELECT payload.calculation_id
            FROM lineage_payloads AS payload
            WHERE EXISTS (
                SELECT 1
                FROM lineage_records AS record
                WHERE record.calculation_id = payload.calculation_id
                  AND record.status = :pending_status
            )
              AND (
                payload.lease_expires_at_utc IS NULL
                OR payload.lease_expires_at_utc < :leased_at_utc
              )
            ORDER BY payload.created_at_utc ASC, payload.calculation_id ASC
            FOR UPDATE OF payload SKIP LOCKED
            LIMIT :limit
        ) AS claimable
        WHERE payload.calculation_id = claimable.calculation_id
        RETURNING
            payload.calculation_id,
            payload.calculation_type,
            payload.request_json,
            payload.response_json,
            payload.details_json,
            payload.attempt_count,
            payload.worker_id,
            payload.leased_at_utc,
            payload.lease_expires_at_utc
        """
    )


def _postgresql_pending_payload_lease_params(
    *,
    worker_id: str,
    leased_at_utc: datetime,
    lease_expires_at_utc: datetime,
    limit: int,
) -> dict[str, object]:
    return {
        "worker_id": worker_id,
        "leased_at_utc": leased_at_utc,
        "lease_expires_at_utc": lease_expires_at_utc,
        "pending_status": LineageStatus.PENDING.value,
        "limit": limit,
    }


def _postgresql_pending_payload_from_row(row: Mapping[str, object]) -> tuple[str, LineagePayload | None]:
    calculation_id = str(row["calculation_id"])
    details = _load_payload_details(str(row["details_json"]), calculation_id=calculation_id)
    if details is None:
        return calculation_id, None
    leased_at_utc = cast(datetime | None, row["leased_at_utc"])
    lease_expires_at_utc = cast(datetime | None, row["lease_expires_at_utc"])
    return (
        calculation_id,
        LineagePayload(
            calculation_id=UUID(calculation_id),
            calculation_type=str(row["calculation_type"]),
            request_json=str(row["request_json"]),
            response_json=str(row["response_json"]),
            details=details,
            attempt_count=int(str(row["attempt_count"])),
            worker_id=None if row["worker_id"] is None else str(row["worker_id"]),
            leased_at_utc=format_timestamp(leased_at_utc),
            lease_expires_at_utc=format_timestamp(lease_expires_at_utc),
        ),
    )


def _load_payload_details(details_json: str, *, calculation_id: str) -> dict[str, str] | None:
    payload = load_json_object_or_none(
        details_json,
        logger=logger,
        payload_name="Lineage payload details",
        identity_name="calculation_id",
        identity_value=calculation_id,
        empty_is_absent=False,
    )
    if payload is None:
        return None
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in payload.items()):
        logger.warning("Lineage payload details are not a string object for calculation_id=%s.", calculation_id)
        return None
    return payload


def _mark_invalid_payload_details(session: Session, calculation_id: str, *, now: datetime) -> None:
    record = session.get(LineageRecordModel, calculation_id)
    if record is not None:
        record.status = LineageStatus.FAILED.value
        record.timestamp_utc = now
        record.error_message = INVALID_LINEAGE_PAYLOAD_DETAILS_MESSAGE
    payload = session.get(LineagePayloadModel, calculation_id)
    if payload is not None:
        payload.worker_id = None
        payload.leased_at_utc = None
        payload.lease_expires_at_utc = None
