from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from typing import Any, Iterator

from sqlalchemy import DateTime, Index, String, Text, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.services.durable_database_engine import create_durable_database_engine
from app.services.durable_schema_creation import create_durable_schema
from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store
from app.services.durable_store_time import format_timestamp


class SourceCorrectionRegistrationStatus(StrEnum):
    CREATED = "created"
    REPLAY = "replay"
    CONFLICT = "conflict"
    REVISION_CONFLICT = "revision_conflict"


class Base(DeclarativeBase):
    pass


class SourceCorrectionEventModel(Base):
    __tablename__ = "analytics_source_correction"
    __table_args__ = (
        Index(
            "ix_source_correction_scope_observed",
            "tenant_id",
            "source_product",
            "target_type",
            "target_id",
            "observed_at_utc",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    correction_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(71), nullable=False)
    source_product: Mapped[str] = mapped_column(String(64), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    impacts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class SourceCorrectionRecord:
    tenant_id: str
    correction_id: str
    request_fingerprint: str
    source_product: str
    source_revision: str
    target_type: str
    target_id: str
    observed_at_utc: str
    request_payload: dict[str, Any]
    state: str
    impacts: list[dict[str, Any]]
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class SourceCorrectionRegistration:
    status: SourceCorrectionRegistrationStatus
    record: SourceCorrectionRecord


class SourceCorrectionStore:
    def __init__(self, database_url: str):
        self._engine = create_durable_database_engine(database_url)
        self._session_factory = sessionmaker(bind=self._engine, future=True)

    def create_schema(self) -> None:
        create_durable_schema(self._engine, Base.metadata)

    def verify_schema(self) -> None:
        from app.adapters.durable_schema.catalog import verify_durable_schema

        verify_durable_schema(self._engine, Base.metadata)

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

    def register(
        self,
        *,
        tenant_id: str,
        correction_id: str,
        request_fingerprint: str,
        request_payload: dict[str, Any],
    ) -> SourceCorrectionRegistration:
        now = datetime.now(timezone.utc)
        observed_at = datetime.fromisoformat(str(request_payload["observed_at_utc"]).replace("Z", "+00:00"))
        row = SourceCorrectionEventModel(
            tenant_id=tenant_id,
            correction_id=correction_id,
            request_fingerprint=request_fingerprint,
            source_product=str(request_payload["source_product"]),
            source_revision=str(request_payload["source_revision"]),
            target_type=str(request_payload["target_type"]),
            target_id=str(request_payload["target_id"]),
            observed_at_utc=observed_at,
            request_json=json.dumps(request_payload, sort_keys=True),
            state="recalculation_pending",
            impacts_json="[]",
            created_at_utc=now,
            updated_at_utc=now,
        )
        session = self._session_factory()
        try:
            _lock_source_correction_scope(
                session,
                tenant_id=tenant_id,
                source_product=row.source_product,
                target_type=row.target_type,
                target_id=row.target_id,
            )
            existing = session.get(SourceCorrectionEventModel, (tenant_id, correction_id))
            existing_registration = _existing_registration(existing, request_fingerprint=request_fingerprint)
            if existing_registration is not None:
                return existing_registration

            latest = session.execute(_latest_scope_statement(row)).scalar_one_or_none()
            if _breaks_revision_chain(latest, observed_at=observed_at, request_payload=request_payload):
                return SourceCorrectionRegistration(
                    SourceCorrectionRegistrationStatus.REVISION_CONFLICT,
                    _record(latest),
                )

            session.add(row)
            session.commit()
            session.refresh(row)
            return SourceCorrectionRegistration(SourceCorrectionRegistrationStatus.CREATED, _record(row))
        except IntegrityError:
            session.rollback()
            existing = session.get(SourceCorrectionEventModel, (tenant_id, correction_id))
            if existing is None:
                raise
            status = (
                SourceCorrectionRegistrationStatus.REPLAY
                if existing.request_fingerprint == request_fingerprint
                else SourceCorrectionRegistrationStatus.CONFLICT
            )
            return SourceCorrectionRegistration(status, _record(existing))
        finally:
            session.close()

    def get(self, *, tenant_id: str, correction_id: str) -> SourceCorrectionRecord | None:
        with self._session() as session:
            row = session.get(SourceCorrectionEventModel, (tenant_id, correction_id))
            return None if row is None else _record(row)

    def has_newer_scope_event(self, record: SourceCorrectionRecord) -> bool:
        observed_at = datetime.fromisoformat(record.observed_at_utc.replace("Z", "+00:00"))
        with self._session() as session:
            statement = select(SourceCorrectionEventModel.correction_id).where(
                SourceCorrectionEventModel.tenant_id == record.tenant_id,
                SourceCorrectionEventModel.source_product == record.source_product,
                SourceCorrectionEventModel.target_type == record.target_type,
                SourceCorrectionEventModel.target_id == record.target_id,
                SourceCorrectionEventModel.observed_at_utc > observed_at,
            )
            return session.execute(statement.limit(1)).scalar_one_or_none() is not None

    def latest_for_scope(
        self,
        *,
        tenant_id: str,
        source_product: str,
        target_type: str,
        target_id: str,
    ) -> SourceCorrectionRecord | None:
        with self._session() as session:
            statement = (
                select(SourceCorrectionEventModel)
                .where(
                    SourceCorrectionEventModel.tenant_id == tenant_id,
                    SourceCorrectionEventModel.source_product == source_product,
                    SourceCorrectionEventModel.target_type == target_type,
                    SourceCorrectionEventModel.target_id == target_id,
                )
                .order_by(
                    SourceCorrectionEventModel.observed_at_utc.desc(),
                    SourceCorrectionEventModel.created_at_utc.desc(),
                )
                .limit(1)
            )
            row = session.execute(statement).scalar_one_or_none()
            return None if row is None else _record(row)

    def update(self, *, tenant_id: str, correction_id: str, state: str, impacts: list[dict[str, Any]]) -> None:
        with self._session() as session:
            row = session.get(SourceCorrectionEventModel, (tenant_id, correction_id))
            if row is None:
                raise KeyError(f"Source correction not found: {correction_id}")
            row.state = state
            row.impacts_json = json.dumps(impacts, sort_keys=True)
            row.updated_at_utc = datetime.now(timezone.utc)

    def cancel_impacts(
        self,
        *,
        tenant_id: str,
        corrected_calculation_ids: set[str],
        failure_code: str,
    ) -> None:
        """Publish cancellation to every correction that shares any cancelled job."""
        with self._session() as session:
            rows = session.execute(
                select(SourceCorrectionEventModel).where(SourceCorrectionEventModel.tenant_id == tenant_id)
            ).scalars()
            now = datetime.now(timezone.utc)
            for row in rows:
                impacts = json.loads(row.impacts_json)
                if not isinstance(impacts, list):
                    continue
                changed = False
                updated_impacts: list[dict[str, Any]] = []
                for stored in impacts:
                    impact = dict(stored)
                    if str(impact.get("corrected_calculation_id")) in corrected_calculation_ids:
                        impact["state"] = "failed"
                        impact["failure_code"] = failure_code
                        changed = True
                    updated_impacts.append(impact)
                if not changed:
                    continue
                row.impacts_json = json.dumps(updated_impacts, sort_keys=True)
                row.state = (
                    "cancelled"
                    if all(
                        str(impact.get("corrected_calculation_id")) in corrected_calculation_ids
                        for impact in updated_impacts
                    )
                    else "partial_failure"
                )
                row.updated_at_utc = now

    def clear_all_records(self) -> None:
        with self._session() as session:
            session.query(SourceCorrectionEventModel).delete()

    def referenced_calculation_ids(self) -> set[str]:
        with self._session() as session:
            rows = session.execute(select(SourceCorrectionEventModel.impacts_json)).all()
        calculation_ids: set[str] = set()
        for (raw_impacts,) in rows:
            impacts = json.loads(raw_impacts)
            if not isinstance(impacts, list):
                continue
            for impact in impacts:
                if not isinstance(impact, dict):
                    continue
                for field_name in ("original_calculation_id", "corrected_calculation_id"):
                    value = impact.get(field_name)
                    if isinstance(value, str):
                        calculation_ids.add(value)
        return calculation_ids


def _record(row: SourceCorrectionEventModel) -> SourceCorrectionRecord:
    request_payload = json.loads(row.request_json)
    impacts = json.loads(row.impacts_json)
    if not isinstance(request_payload, dict) or not isinstance(impacts, list):
        raise ValueError(f"Stored source correction payload is invalid: {row.correction_id}")
    return SourceCorrectionRecord(
        tenant_id=row.tenant_id,
        correction_id=row.correction_id,
        request_fingerprint=row.request_fingerprint,
        source_product=row.source_product,
        source_revision=row.source_revision,
        target_type=row.target_type,
        target_id=row.target_id,
        observed_at_utc=format_timestamp(row.observed_at_utc) or "",
        request_payload=request_payload,
        state=row.state,
        impacts=impacts,
        created_at_utc=format_timestamp(row.created_at_utc) or "",
        updated_at_utc=format_timestamp(row.updated_at_utc) or "",
    )


def _latest_scope_statement(row: SourceCorrectionEventModel):
    return (
        select(SourceCorrectionEventModel)
        .where(
            SourceCorrectionEventModel.tenant_id == row.tenant_id,
            SourceCorrectionEventModel.source_product == row.source_product,
            SourceCorrectionEventModel.target_type == row.target_type,
            SourceCorrectionEventModel.target_id == row.target_id,
        )
        .order_by(
            SourceCorrectionEventModel.observed_at_utc.desc(),
            SourceCorrectionEventModel.created_at_utc.desc(),
        )
        .limit(1)
    )


def _existing_registration(
    existing: SourceCorrectionEventModel | None,
    *,
    request_fingerprint: str,
) -> SourceCorrectionRegistration | None:
    if existing is None:
        return None
    status = (
        SourceCorrectionRegistrationStatus.REPLAY
        if existing.request_fingerprint == request_fingerprint
        else SourceCorrectionRegistrationStatus.CONFLICT
    )
    return SourceCorrectionRegistration(status, _record(existing))


def _breaks_revision_chain(
    latest: SourceCorrectionEventModel | None,
    *,
    observed_at: datetime,
    request_payload: dict[str, Any],
) -> bool:
    return (
        latest is not None
        and observed_at >= _as_utc(latest.observed_at_utc)
        and request_payload.get("supersedes_source_revision") != latest.source_revision
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _lock_source_correction_scope(
    session: Session,
    *,
    tenant_id: str,
    source_product: str,
    target_type: str,
    target_id: str,
) -> None:
    if session.bind is None:
        return
    if session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
        return
    if session.bind.dialect.name == "postgresql":
        identity = json.dumps(
            {
                "scope": "source-correction-admission",
                "source_product": source_product,
                "target_id": target_id,
                "target_type": target_type,
                "tenant_id": tenant_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        unsigned = int(sha256(identity.encode("utf-8")).hexdigest()[:16], 16)
        lock_key = unsigned if unsigned < 2**63 else unsigned - 2**64
        session.execute(select(func.pg_advisory_xact_lock(lock_key)))


_store_cache: dict[str, SourceCorrectionStore] = {}


def get_source_correction_store(*, database_url: str | None = None) -> SourceCorrectionStore:
    return resolve_runtime_store(cache=_store_cache, factory=SourceCorrectionStore, database_url=database_url)


source_correction_store = RuntimeStoreProxy(get_source_correction_store)
