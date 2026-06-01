from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store

logger = logging.getLogger(__name__)


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ExecutionStageStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


class ExecutionRegistrationStatus(StrEnum):
    CREATED = "created"
    REPLAY = "replay"
    CONFLICT = "conflict"


class Base(DeclarativeBase):
    pass


class AnalyticsExecutionModel(Base):
    __tablename__ = "analytics_execution"

    calculation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analytics_type: Mapped[str] = mapped_column(String(64), nullable=False)
    portfolio_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_window_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    input_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    calculation_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stages: Mapped[list["AnalyticsExecutionStageModel"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
    )


class AnalyticsExecutionStageModel(Base):
    __tablename__ = "analytics_execution_stage"

    calculation_id: Mapped[str] = mapped_column(
        ForeignKey("analytics_execution.calculation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    stage_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    execution: Mapped[AnalyticsExecutionModel] = relationship(back_populates="stages")


class AnalyticsUpstreamSnapshotModel(Base):
    __tablename__ = "analytics_upstream_snapshot"
    __table_args__ = (
        Index(
            "ix_upstream_snapshot_calculation_created_at",
            "calculation_id",
            "created_at_utc",
        ),
    )

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    calculation_id: Mapped[str] = mapped_column(
        ForeignKey("analytics_execution.calculation_id", ondelete="CASCADE"),
        nullable=False,
    )
    upstream_endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    source_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    as_of_date: Mapped[str] = mapped_column(String(32), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    response_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    paging_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class ExecutionStageRecord:
    stage_name: str
    status: ExecutionStageStatus
    started_at_utc: str | None
    completed_at_utc: str | None
    details: dict[str, Any] | None
    error_message: str | None


@dataclass(frozen=True)
class UpstreamSnapshotRecord:
    snapshot_id: str
    upstream_endpoint: str
    source_identifier: str
    as_of_date: str
    request_fingerprint: str
    response_fingerprint: str
    retrieval_status: str
    paging_metadata: dict[str, Any] | None
    created_at_utc: str


@dataclass(frozen=True)
class ExecutionRecord:
    calculation_id: UUID
    analytics_type: str
    portfolio_id: str | None
    execution_mode: str
    status: ExecutionStatus
    requested_window: dict[str, Any]
    input_fingerprint: str | None
    calculation_hash: str | None
    error_message: str | None
    created_at_utc: str
    started_at_utc: str | None
    completed_at_utc: str | None
    stages: list[ExecutionStageRecord]
    upstream_snapshots: list[UpstreamSnapshotRecord]


@dataclass(frozen=True)
class ExecutionRegistrationResult:
    status: ExecutionRegistrationStatus
    existing_status: ExecutionStatus | None = None
    existing_execution_mode: str | None = None


def _serialize_paging_metadata(paging_metadata: dict[str, Any] | None) -> str | None:
    return json.dumps(paging_metadata, sort_keys=True) if paging_metadata is not None else None


def _coerce_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _coerce_utc_datetime(value).isoformat().replace("+00:00", "Z")


def _normalize_filter_datetime(value: datetime, *, dialect_name: str) -> datetime:
    normalized = _coerce_utc_datetime(value)
    if dialect_name == "sqlite":
        return normalized.replace(tzinfo=None)
    return normalized


class ExecutionRegistry:
    def __init__(self, database_url: str):
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self._engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._session_factory = sessionmaker(bind=self._engine, future=True)

    def create_schema(self) -> None:
        Base.metadata.create_all(self._engine)
        self._ensure_runtime_indexes()

    def ping(self) -> None:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def list_table_names(self) -> tuple[str, ...]:
        from sqlalchemy import inspect

        return tuple(inspect(self._engine).get_table_names())

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
            session.query(AnalyticsUpstreamSnapshotModel).delete()
            session.query(AnalyticsExecutionStageModel).delete()
            session.query(AnalyticsExecutionModel).delete()

    def delete_execution(self, calculation_id: UUID) -> None:
        with self._session() as session:
            execution = session.get(AnalyticsExecutionModel, str(calculation_id))
            if execution is not None:
                session.delete(execution)

    def list_terminal_execution_ids_older_than(self, older_than: datetime) -> list[str]:
        with self._session() as session:
            dialect_name = session.bind.dialect.name if session.bind is not None else ""
            cutoff = _normalize_filter_datetime(older_than, dialect_name=dialect_name)
            statement = (
                select(AnalyticsExecutionModel.calculation_id)
                .where(
                    AnalyticsExecutionModel.status.in_([ExecutionStatus.COMPLETE.value, ExecutionStatus.FAILED.value])
                )
                .where(AnalyticsExecutionModel.completed_at_utc.is_not(None))
                .where(AnalyticsExecutionModel.completed_at_utc <= cutoff)
                .order_by(AnalyticsExecutionModel.completed_at_utc.asc(), AnalyticsExecutionModel.created_at_utc.asc())
            )
            return [row[0] for row in session.execute(statement).all()]

    def delete_executions(self, calculation_ids: list[str]) -> int:
        if not calculation_ids:
            return 0
        with self._session() as session:
            rows = (
                session.execute(
                    select(AnalyticsExecutionModel).where(AnalyticsExecutionModel.calculation_id.in_(calculation_ids))
                )
                .scalars()
                .all()
            )
            for row in rows:
                session.delete(row)
            return len(rows)

    def create_execution(
        self,
        *,
        calculation_id: UUID,
        analytics_type: str,
        portfolio_id: str | None,
        execution_mode: str = "sync",
        requested_window: dict[str, Any] | None = None,
        input_fingerprint: str | None = None,
        calculation_hash: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._session() as session:
            execution = AnalyticsExecutionModel(
                calculation_id=str(calculation_id),
                analytics_type=analytics_type,
                portfolio_id=portfolio_id,
                execution_mode=execution_mode,
                status=ExecutionStatus.PENDING.value,
                requested_window_json=json.dumps(requested_window or {}, sort_keys=True),
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
                error_message=None,
                created_at_utc=now,
                started_at_utc=None,
                completed_at_utc=None,
            )
            session.merge(execution)

    def register_execution(
        self,
        *,
        calculation_id: UUID,
        analytics_type: str,
        portfolio_id: str | None,
        execution_mode: str = "sync",
        requested_window: dict[str, Any] | None = None,
        input_fingerprint: str | None = None,
        calculation_hash: str | None = None,
    ) -> ExecutionRegistrationResult:
        now = datetime.now(timezone.utc)
        requested_window_json = json.dumps(requested_window or {}, sort_keys=True)
        execution = AnalyticsExecutionModel(
            calculation_id=str(calculation_id),
            analytics_type=analytics_type,
            portfolio_id=portfolio_id,
            execution_mode=execution_mode,
            status=ExecutionStatus.PENDING.value,
            requested_window_json=requested_window_json,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            error_message=None,
            created_at_utc=now,
            started_at_utc=None,
            completed_at_utc=None,
        )

        session = self._session_factory()
        try:
            session.add(execution)
            session.commit()
            return ExecutionRegistrationResult(status=ExecutionRegistrationStatus.CREATED)
        except IntegrityError:
            session.rollback()
            existing = session.get(AnalyticsExecutionModel, str(calculation_id))
            if existing is None:
                raise
            if self._is_replay_of_existing_execution(
                existing=existing,
                analytics_type=analytics_type,
                portfolio_id=portfolio_id,
                execution_mode=execution_mode,
                requested_window_json=requested_window_json,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            ):
                return ExecutionRegistrationResult(
                    status=ExecutionRegistrationStatus.REPLAY,
                    existing_status=ExecutionStatus(existing.status),
                    existing_execution_mode=existing.execution_mode,
                )
            return ExecutionRegistrationResult(
                status=ExecutionRegistrationStatus.CONFLICT,
                existing_status=ExecutionStatus(existing.status),
                existing_execution_mode=existing.execution_mode,
            )
        finally:
            session.close()

    def mark_running(self, calculation_id: UUID) -> None:
        with self._session() as session:
            execution = self._get_execution_model(session, calculation_id)
            execution.status = ExecutionStatus.RUNNING.value
            execution.started_at_utc = execution.started_at_utc or datetime.now(timezone.utc)
            execution.completed_at_utc = None
            execution.error_message = None

    def mark_complete(self, calculation_id: UUID) -> None:
        with self._session() as session:
            execution = self._get_execution_model(session, calculation_id)
            now = datetime.now(timezone.utc)
            execution.status = ExecutionStatus.COMPLETE.value
            execution.started_at_utc = execution.started_at_utc or now
            execution.completed_at_utc = now
            execution.error_message = None

    def mark_failed(self, calculation_id: UUID, error_message: str) -> None:
        with self._session() as session:
            execution = self._get_execution_model(session, calculation_id)
            now = datetime.now(timezone.utc)
            execution.status = ExecutionStatus.FAILED.value
            execution.started_at_utc = execution.started_at_utc or now
            execution.completed_at_utc = now
            execution.error_message = error_message

    def update_execution_identity(
        self,
        calculation_id: UUID,
        *,
        input_fingerprint: str | None,
        calculation_hash: str | None,
    ) -> None:
        with self._session() as session:
            execution = self._get_execution_model(session, calculation_id)
            execution.input_fingerprint = input_fingerprint
            execution.calculation_hash = calculation_hash

    def update_execution_contract(
        self,
        calculation_id: UUID,
        *,
        execution_mode: str | None = None,
        requested_window: dict[str, Any] | None = None,
    ) -> None:
        with self._session() as session:
            execution = self._get_execution_model(session, calculation_id)
            if execution_mode is not None:
                execution.execution_mode = execution_mode
            if requested_window is not None:
                execution.requested_window_json = json.dumps(requested_window, sort_keys=True)

    def start_stage(self, calculation_id: UUID, stage_name: str, details: dict[str, Any] | None = None) -> None:
        with self._session() as session:
            self._get_execution_model(session, calculation_id)
            stage = session.get(AnalyticsExecutionStageModel, (str(calculation_id), stage_name))
            now = datetime.now(timezone.utc)
            if stage is None:
                stage = AnalyticsExecutionStageModel(
                    calculation_id=str(calculation_id),
                    stage_name=stage_name,
                    status=ExecutionStageStatus.IN_PROGRESS.value,
                    started_at_utc=now,
                    completed_at_utc=None,
                    details_json=json.dumps(details, sort_keys=True) if details is not None else None,
                    error_message=None,
                )
            else:
                stage.status = ExecutionStageStatus.IN_PROGRESS.value
                stage.started_at_utc = now
                stage.completed_at_utc = None
                stage.details_json = json.dumps(details, sort_keys=True) if details is not None else stage.details_json
                stage.error_message = None
            session.merge(stage)

    def complete_stage(self, calculation_id: UUID, stage_name: str, details: dict[str, Any] | None = None) -> None:
        with self._session() as session:
            stage = self._get_stage_model(session, calculation_id, stage_name)
            now = datetime.now(timezone.utc)
            stage.status = ExecutionStageStatus.COMPLETE.value
            stage.started_at_utc = stage.started_at_utc or now
            stage.completed_at_utc = now
            if details is not None:
                stage.details_json = json.dumps(details, sort_keys=True)
            stage.error_message = None

    def fail_stage(self, calculation_id: UUID, stage_name: str, error_message: str) -> None:
        with self._session() as session:
            stage = self._get_stage_model(session, calculation_id, stage_name)
            now = datetime.now(timezone.utc)
            stage.status = ExecutionStageStatus.FAILED.value
            stage.started_at_utc = stage.started_at_utc or now
            stage.completed_at_utc = now
            stage.error_message = error_message

    def fail_in_progress_stages(self, calculation_id: UUID, error_message: str) -> None:
        with self._session() as session:
            self._get_execution_model(session, calculation_id)
            statement = select(AnalyticsExecutionStageModel).where(
                (AnalyticsExecutionStageModel.calculation_id == str(calculation_id))
                & (AnalyticsExecutionStageModel.status == ExecutionStageStatus.IN_PROGRESS.value)
            )
            now = datetime.now(timezone.utc)
            rows = session.execute(statement).scalars().all()
            for stage in rows:
                stage.status = ExecutionStageStatus.FAILED.value
                stage.started_at_utc = stage.started_at_utc or now
                stage.completed_at_utc = now
                stage.error_message = error_message

    def get_execution(self, calculation_id: UUID) -> ExecutionRecord | None:
        with self._session() as session:
            statement = self._build_execution_lookup_statement(calculation_id)
            execution = session.execute(statement).scalar_one_or_none()
            if execution is None:
                return None
            stage_records = [
                ExecutionStageRecord(
                    stage_name=stage.stage_name,
                    status=ExecutionStageStatus(stage.status),
                    started_at_utc=_format_timestamp(stage.started_at_utc),
                    completed_at_utc=_format_timestamp(stage.completed_at_utc),
                    details=_load_json_object(
                        stage.details_json,
                        calculation_id=execution.calculation_id,
                        payload_name=f"stage {stage.stage_name} details",
                    ),
                    error_message=stage.error_message,
                )
                for stage in sorted(execution.stages, key=lambda item: item.stage_name)
            ]
            return ExecutionRecord(
                calculation_id=UUID(execution.calculation_id),
                analytics_type=execution.analytics_type,
                portfolio_id=execution.portfolio_id,
                execution_mode=execution.execution_mode,
                status=ExecutionStatus(execution.status),
                requested_window=_load_json_object(
                    execution.requested_window_json,
                    calculation_id=execution.calculation_id,
                    payload_name="requested window",
                )
                or {},
                input_fingerprint=execution.input_fingerprint,
                calculation_hash=execution.calculation_hash,
                error_message=execution.error_message,
                created_at_utc=_format_timestamp(execution.created_at_utc) or "",
                started_at_utc=_format_timestamp(execution.started_at_utc),
                completed_at_utc=_format_timestamp(execution.completed_at_utc),
                stages=stage_records,
                upstream_snapshots=self.list_upstream_snapshots(calculation_id),
            )

    def record_upstream_snapshot(
        self,
        *,
        calculation_id: UUID,
        snapshot_id: str,
        upstream_endpoint: str,
        source_identifier: str,
        as_of_date: str,
        request_fingerprint: str,
        response_fingerprint: str,
        retrieval_status: str,
        paging_metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._session() as session:
            self._get_execution_model(session, calculation_id)
            try:
                with session.begin_nested():
                    session.add(
                        AnalyticsUpstreamSnapshotModel(
                            snapshot_id=snapshot_id,
                            calculation_id=str(calculation_id),
                            upstream_endpoint=upstream_endpoint,
                            source_identifier=source_identifier,
                            as_of_date=as_of_date,
                            request_fingerprint=request_fingerprint,
                            response_fingerprint=response_fingerprint,
                            retrieval_status=retrieval_status,
                            paging_metadata_json=_serialize_paging_metadata(paging_metadata),
                            created_at_utc=datetime.now(timezone.utc),
                        )
                    )
                    session.flush()
            except IntegrityError:
                pass

    def record_upstream_snapshots(
        self,
        *,
        calculation_id: UUID,
        snapshots: list[dict[str, Any]],
    ) -> None:
        if not snapshots:
            return
        with self._session() as session:
            self._get_execution_model(session, calculation_id)
            snapshot_ids = [snapshot["snapshot_id"] for snapshot in snapshots]
            existing_snapshot_ids = {
                row[0]
                for row in session.execute(
                    select(AnalyticsUpstreamSnapshotModel.snapshot_id).where(
                        AnalyticsUpstreamSnapshotModel.snapshot_id.in_(snapshot_ids)
                    )
                ).all()
            }
            created_at = datetime.now(timezone.utc)
            for snapshot in snapshots:
                if snapshot["snapshot_id"] in existing_snapshot_ids:
                    continue
                try:
                    with session.begin_nested():
                        session.add(
                            AnalyticsUpstreamSnapshotModel(
                                snapshot_id=snapshot["snapshot_id"],
                                calculation_id=str(calculation_id),
                                upstream_endpoint=snapshot["upstream_endpoint"],
                                source_identifier=snapshot["source_identifier"],
                                as_of_date=snapshot["as_of_date"],
                                request_fingerprint=snapshot["request_fingerprint"],
                                response_fingerprint=snapshot["response_fingerprint"],
                                retrieval_status=snapshot["retrieval_status"],
                                paging_metadata_json=_serialize_paging_metadata(snapshot.get("paging_metadata")),
                                created_at_utc=created_at,
                            )
                        )
                        session.flush()
                        existing_snapshot_ids.add(snapshot["snapshot_id"])
                except IntegrityError:
                    existing_snapshot_ids.add(snapshot["snapshot_id"])
                    continue

    def list_upstream_snapshots(self, calculation_id: UUID) -> list[UpstreamSnapshotRecord]:
        with self._session() as session:
            statement = self._build_upstream_snapshots_statement(calculation_id)
            rows = session.execute(statement).scalars().all()
            return [
                UpstreamSnapshotRecord(
                    snapshot_id=row.snapshot_id,
                    upstream_endpoint=row.upstream_endpoint,
                    source_identifier=row.source_identifier,
                    as_of_date=row.as_of_date,
                    request_fingerprint=row.request_fingerprint,
                    response_fingerprint=row.response_fingerprint,
                    retrieval_status=row.retrieval_status,
                    paging_metadata=_load_json_object(
                        row.paging_metadata_json,
                        calculation_id=row.calculation_id,
                        payload_name=f"upstream snapshot {row.snapshot_id} paging metadata",
                    ),
                    created_at_utc=_format_timestamp(row.created_at_utc) or "",
                )
                for row in rows
            ]

    def list_upstream_snapshot_ids(self, calculation_id: UUID) -> set[str]:
        with self._session() as session:
            rows = session.execute(
                select(AnalyticsUpstreamSnapshotModel.snapshot_id).where(
                    AnalyticsUpstreamSnapshotModel.calculation_id == str(calculation_id)
                )
            ).all()
            return {row[0] for row in rows}

    def _build_execution_lookup_statement(self, calculation_id: UUID):
        return select(AnalyticsExecutionModel).where(AnalyticsExecutionModel.calculation_id == str(calculation_id))

    def _build_upstream_snapshots_statement(self, calculation_id: UUID):
        return (
            select(AnalyticsUpstreamSnapshotModel)
            .where(AnalyticsUpstreamSnapshotModel.calculation_id == str(calculation_id))
            .order_by(AnalyticsUpstreamSnapshotModel.created_at_utc.asc())
        )

    def _get_execution_model(self, session: Session, calculation_id: UUID) -> AnalyticsExecutionModel:
        execution = session.get(AnalyticsExecutionModel, str(calculation_id))
        if execution is None:
            raise KeyError(f"Execution record not found: {calculation_id}")
        return execution

    def _get_stage_model(self, session: Session, calculation_id: UUID, stage_name: str) -> AnalyticsExecutionStageModel:
        stage = session.get(AnalyticsExecutionStageModel, (str(calculation_id), stage_name))
        if stage is None:
            raise KeyError(f"Execution stage not found: {calculation_id}/{stage_name}")
        return stage

    def _ensure_runtime_indexes(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("DROP INDEX IF EXISTS ix_analytics_upstream_snapshot_calculation_id"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_upstream_snapshot_calculation_created_at "
                    "ON analytics_upstream_snapshot (calculation_id, created_at_utc)"
                )
            )

    @staticmethod
    def _is_replay_of_existing_execution(
        *,
        existing: AnalyticsExecutionModel,
        analytics_type: str,
        portfolio_id: str | None,
        execution_mode: str,
        requested_window_json: str,
        input_fingerprint: str | None,
        calculation_hash: str | None,
    ) -> bool:
        return (
            existing.analytics_type == analytics_type
            and existing.portfolio_id == portfolio_id
            and existing.execution_mode == execution_mode
            and existing.requested_window_json == requested_window_json
            and existing.input_fingerprint == input_fingerprint
            and existing.calculation_hash == calculation_hash
        )


_store_cache: dict[str, ExecutionRegistry] = {}


def get_execution_registry(*, database_url: str | None = None) -> ExecutionRegistry:
    return resolve_runtime_store(cache=_store_cache, factory=ExecutionRegistry, database_url=database_url)


execution_registry = RuntimeStoreProxy(get_execution_registry)


def _load_json_object(raw_payload: str | None, *, calculation_id: str, payload_name: str) -> dict[str, Any] | None:
    if not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        logger.warning(
            "Execution registry %s invalid JSON for calculation_id=%s.",
            payload_name,
            calculation_id,
        )
        return None
    if not isinstance(payload, dict):
        logger.warning(
            "Execution registry %s is not an object for calculation_id=%s.",
            payload_name,
            calculation_id,
        )
        return None
    return payload
