from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.core.config import get_settings


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


@dataclass(frozen=True)
class ExecutionStageRecord:
    stage_name: str
    status: ExecutionStageStatus
    started_at_utc: str | None
    completed_at_utc: str | None
    details: dict[str, Any] | None
    error_message: str | None


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


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ExecutionRegistry:
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
            session.query(AnalyticsExecutionStageModel).delete()
            session.query(AnalyticsExecutionModel).delete()

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

    def get_execution(self, calculation_id: UUID) -> ExecutionRecord | None:
        with self._session() as session:
            statement = select(AnalyticsExecutionModel).where(
                AnalyticsExecutionModel.calculation_id == str(calculation_id)
            )
            execution = session.execute(statement).scalar_one_or_none()
            if execution is None:
                return None
            stage_records = [
                ExecutionStageRecord(
                    stage_name=stage.stage_name,
                    status=ExecutionStageStatus(stage.status),
                    started_at_utc=_format_timestamp(stage.started_at_utc),
                    completed_at_utc=_format_timestamp(stage.completed_at_utc),
                    details=json.loads(stage.details_json) if stage.details_json else None,
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
                requested_window=json.loads(execution.requested_window_json),
                input_fingerprint=execution.input_fingerprint,
                calculation_hash=execution.calculation_hash,
                error_message=execution.error_message,
                created_at_utc=_format_timestamp(execution.created_at_utc) or "",
                started_at_utc=_format_timestamp(execution.started_at_utc),
                completed_at_utc=_format_timestamp(execution.completed_at_utc),
                stages=stage_records,
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


settings = get_settings()
execution_registry = ExecutionRegistry(settings.LINEAGE_METADATA_DATABASE_URL)
