from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.composite_materialization_records import CompositeMaterializationModel, MaterializationBase
from app.adapters.composite_materialization_schema import require_materialization_schema
from app.adapters.composite_materialization_view_upgrade import upgrade_materialization_return_views
from app.models.composite_materialization import (
    CompositeMaterializationCommand,
    CompositeMaterializationState,
    CompositeMemberMaterializationOutcome,
)
from app.models.composites import CompositeMemberReturnFact
from app.services.composite_materialization.progress_policy import (
    require_progress_transition,
    require_retained_progress,
)
from app.services.composite_materialization.records import MaterializationRecord
from app.services.composite_materialization.source_contract import PinnedCompositeSource
from app.services.composite_metadata_store import (
    CompositeMemberReturnFactPublicationModel,
    _find_member_return_fact_publication,
    _lock_composite_definition_identity,
    _lock_composite_tenant_identity,
    _serialize_fact_families,
)
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
from app.services.durable_database_engine import create_durable_database_engine
from app.services.durable_schema_creation import create_durable_schema
from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store
from core.errors import APIConflictError, APIError, APINotFoundError, APIUnprocessableEntityError
from core.monetary_input import validate_calculated_money_model


def _tenant(tenant_id: str) -> str:
    return require_composite_tenant_authority(admitted_tenant_authority(tenant_id)).tenant_id


def _command_json(command: CompositeMaterializationCommand) -> str:
    return json.dumps(command.immutable_payload(), sort_keys=True, separators=(",", ":"))


class CompositeMaterializationStore:
    def __init__(self, database_url: str, *, connection: Connection | None = None):
        self._owns_engine = connection is None
        self._engine = connection.engine if connection is not None else create_durable_database_engine(database_url)
        self._session_factory = sessionmaker(
            bind=connection if connection is not None else self._engine,
            future=True,
            join_transaction_mode="create_savepoint",
        )

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()

    def create_schema(self) -> None:
        create_durable_schema(
            self._engine,
            MaterializationBase.metadata,
            schema_preflights=(upgrade_materialization_return_views, require_materialization_schema),
        )

    @contextmanager
    def _write_session(self, *, tenant_id: str, composite_id: str) -> Iterator[Session]:
        with self._session_factory() as session:
            try:
                if not self._owns_engine:
                    session.connection()  # Join the already-started outer transaction.
                _lock_composite_tenant_identity(session, tenant_id, exclusive=False)
                _lock_composite_definition_identity(
                    session, tenant_id=tenant_id, composite_id=composite_id, exclusive=True
                )
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def register(
        self, command: CompositeMaterializationCommand, *, tenant_id: str, actor_id: str
    ) -> MaterializationRecord:
        tenant_id = _tenant(tenant_id)
        with self._write_session(tenant_id=tenant_id, composite_id=command.composite_id) as session:
            existing = session.get(CompositeMaterializationModel, (tenant_id, str(command.materialization_id)))
            if existing is not None:
                return self._replay(existing, command, session=session)
            _require_new_chronology(session, command, tenant_id=tenant_id)
            session.add(
                CompositeMaterializationModel(
                    tenant_id=tenant_id,
                    materialization_id=str(command.materialization_id),
                    composite_id=command.composite_id,
                    return_view=command.return_view.value,
                    reporting_currency=command.reporting_currency,
                    restatement_sequence=command.restatement_sequence,
                    period_start=command.period_start,
                    period_end=command.period_end,
                    command_json=_command_json(command),
                    actor_id=actor_id,
                    state="WAITING",
                    reason_code="COMPOSITE_SOURCE_PENDING",
                    outcomes_json="[]",
                    revision=0,
                )
            )
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                with self._session_factory() as collision_session:
                    collision = collision_session.get(
                        CompositeMaterializationModel, (tenant_id, str(command.materialization_id))
                    )
                    if collision is not None:
                        return self._replay(collision, command, session=collision_session)
                raise APIConflictError(
                    "Composite fact chronology is already reserved.",
                    error_code="COMPOSITE_MATERIALIZATION_SCOPE_CONFLICT",
                ) from exc
        return self.get(command.materialization_id, tenant_id=tenant_id)

    def _replay(
        self, row: CompositeMaterializationModel, command: CompositeMaterializationCommand, *, session: Session
    ) -> MaterializationRecord:
        if row.command_json != _command_json(command):
            raise APIConflictError(
                "Materialization command content conflicts with its immutable identity.",
                error_code="COMPOSITE_MATERIALIZATION_CONTENT_CONFLICT",
            )
        return self._record(row, session=session)

    def get(self, materialization_id: UUID, *, tenant_id: str) -> MaterializationRecord:
        with self._session_factory() as session:
            row = session.get(CompositeMaterializationModel, (_tenant(tenant_id), str(materialization_id)))
            if row is None:
                raise APINotFoundError("Composite materialization was not found.")
            return self._record(row, session=session)

    def get_many(self, materialization_ids: list[UUID], *, tenant_id: str) -> list[MaterializationRecord]:
        """Read a bounded vector and all publication checks from one database snapshot."""
        if not 1 <= len(materialization_ids) <= 120 or len(set(materialization_ids)) != len(materialization_ids):
            raise ValueError("Retained vector requires 1..120 unique materialization identities")
        tenant_id = _tenant(tenant_id)
        with self._session_factory() as session:
            if self._engine.dialect.name == "postgresql":
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            else:
                # SQLite's legacy driver does not begin a snapshot for SELECT alone.
                session.connection().exec_driver_sql("BEGIN")
            records = []
            for identity in materialization_ids:
                row = session.get(CompositeMaterializationModel, (tenant_id, str(identity)))
                if row is None:
                    raise APINotFoundError("Composite materialization was not found.")
                records.append(self._record(row, session=session))
            return records

    def get_for_member_return_facts(
        self, facts: list[CompositeMemberReturnFact], *, tenant_id: str
    ) -> list[MaterializationRecord]:
        """Recover exact immutable method custody, never the current definition.

        Facts are selected by the metadata owner. This owner revalidates the
        matching receipts and publication invariants in one read snapshot.
        """
        scopes = list(dict.fromkeys(_financial_scope(fact) for fact in facts))
        dimensions = tuple_(
            CompositeMaterializationModel.composite_id,
            CompositeMaterializationModel.return_view,
            CompositeMaterializationModel.reporting_currency,
            CompositeMaterializationModel.restatement_sequence,
            CompositeMaterializationModel.period_start,
            CompositeMaterializationModel.period_end,
        )
        with self._session_factory() as session:
            _begin_read_snapshot(session, self._engine.dialect.name)
            records = {}
            for offset in range(0, len(scopes), 100):
                rows = session.scalars(
                    select(CompositeMaterializationModel).where(
                        CompositeMaterializationModel.tenant_id == _tenant(tenant_id),
                        dimensions.in_(scopes[offset : offset + 100]),
                    )
                )
                for row in rows:
                    record = self._record(row, session=session)
                    records[_financial_scope(record.command)] = record
            if set(records) != set(scopes):
                raise APIUnprocessableEntityError(
                    "Selected model-fee facts require their exact retained method receipts.",
                    error_code="COMPOSITE_MODEL_FEE_METHOD_CONTEXT_UNAVAILABLE",
                )
            return [records[scope] for scope in scopes]

    def save(
        self,
        materialization_id: UUID,
        *,
        tenant_id: str,
        expected_revision: int,
        source: PinnedCompositeSource | None,
        outcomes: list[CompositeMemberMaterializationOutcome],
        state: CompositeMaterializationState,
        reason_code: str | None,
    ) -> MaterializationRecord:
        tenant_id = _tenant(tenant_id)
        composite_id = self.get(materialization_id, tenant_id=tenant_id).command.composite_id
        with self._write_session(tenant_id=tenant_id, composite_id=composite_id) as session:
            row = session.get(CompositeMaterializationModel, (tenant_id, str(materialization_id)))
            if row is None or row.revision != expected_revision:
                raise APIConflictError(
                    "Materialization progress changed; reload before retrying.",
                    error_code="COMPOSITE_MATERIALIZATION_REVISION_CONFLICT",
                )
            previous = self._record(row, session=session)
            require_progress_transition(
                command=previous.command,
                tenant_id=tenant_id,
                prior_source=previous.source,
                prior_outcomes=previous.outcomes,
                prior_state=previous.state,
                source=source,
                outcomes=outcomes,
                state=state,
            )
            if state == CompositeMaterializationState.COMPLETE:
                _require_completed_publication(session, previous.command, outcomes, tenant_id=tenant_id)
            result = session.execute(
                update(CompositeMaterializationModel)
                .where(
                    CompositeMaterializationModel.tenant_id == _tenant(tenant_id),
                    CompositeMaterializationModel.materialization_id == str(materialization_id),
                    CompositeMaterializationModel.revision == expected_revision,
                    CompositeMaterializationModel.state != CompositeMaterializationState.COMPLETE.value,
                )
                .values(
                    source_json=source.model_dump_json() if source is not None else None,
                    outcomes_json=json.dumps([item.model_dump(mode="json") for item in outcomes], sort_keys=True),
                    state=state.value,
                    reason_code=reason_code,
                    revision=expected_revision + 1,
                )
            )
            if result.rowcount != 1:
                raise APIConflictError(
                    "Materialization progress changed; reload before retrying.",
                    error_code="COMPOSITE_MATERIALIZATION_REVISION_CONFLICT",
                )
        return self.get(materialization_id, tenant_id=tenant_id)

    def _record(self, row: CompositeMaterializationModel, *, session: Session) -> MaterializationRecord:
        try:
            record = _materialization_record(row)
            _require_record_scope(row, record)
            require_retained_progress(
                command=record.command,
                tenant_id=row.tenant_id,
                source=record.source,
                outcomes=record.outcomes,
                state=record.state,
            )
            if record.state == CompositeMaterializationState.COMPLETE:
                _require_completed_publication(session, record.command, record.outcomes, tenant_id=row.tenant_id)
            return record
        except (ValueError, KeyError, TypeError) as exc:
            raise APIError(
                status_code=503,
                detail="Retained materialization evidence failed validation; reviewed recovery is required.",
                error_code="COMPOSITE_MATERIALIZATION_RETAINED_EVIDENCE_REFUSED",
                retryable=False,
            ) from exc


def _materialization_record(row: CompositeMaterializationModel) -> MaterializationRecord:
    return MaterializationRecord(
        command=CompositeMaterializationCommand.model_validate(
            {
                **json.loads(row.command_json),
                "calculation_id": row.materialization_id,
            }
        ),
        actor_id=row.actor_id,
        source=PinnedCompositeSource.model_validate_json(row.source_json) if row.source_json else None,
        outcomes=[
            validate_calculated_money_model(CompositeMemberMaterializationOutcome, item)
            for item in json.loads(row.outcomes_json)
        ],
        state=CompositeMaterializationState(row.state),
        reason_code=row.reason_code,
        revision=row.revision,
    )


def _begin_read_snapshot(session: Session, dialect: str) -> None:
    if dialect == "postgresql":
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    else:
        session.connection().exec_driver_sql("BEGIN")


def _financial_scope(value):
    return (
        value.composite_id,
        value.return_view.value,
        value.reporting_currency,
        value.restatement_sequence,
        value.period_start,
        value.period_end,
    )


def _require_record_scope(row: CompositeMaterializationModel, record: MaterializationRecord) -> None:
    command = record.command
    actual = (
        row.materialization_id,
        row.composite_id,
        row.return_view,
        row.reporting_currency,
        row.restatement_sequence,
        row.period_start,
        row.period_end,
    )
    expected = (
        str(command.materialization_id),
        command.composite_id,
        command.return_view.value,
        command.reporting_currency,
        command.restatement_sequence,
        command.period_start,
        command.period_end,
    )
    if actual != expected or row.tenant_id != _tenant(row.tenant_id):
        raise ValueError("Retained row dimensions differ from the immutable command")
    if not row.actor_id or row.actor_id != row.actor_id.strip() or len(row.actor_id) > 128:
        raise ValueError("Retained actor authority is malformed")
    if type(row.revision) is not int or row.revision < 0:
        raise ValueError("Retained progress revision is malformed")


def _require_new_chronology(session: Session, command: CompositeMaterializationCommand, *, tenant_id: str) -> None:
    latest = []
    for model in (CompositeMaterializationModel, CompositeMemberReturnFactPublicationModel):
        sequence = session.scalar(
            select(func.max(model.restatement_sequence)).where(
                model.tenant_id == tenant_id,
                model.composite_id == command.composite_id,
                model.return_view == command.return_view.value,
                model.reporting_currency == command.reporting_currency,
            )
        )
        latest.append(sequence or 0)
    if command.restatement_sequence <= max(latest):
        raise APIConflictError(
            "Composite fact chronology is already reserved or superseded.",
            error_code="COMPOSITE_MATERIALIZATION_SCOPE_CONFLICT",
        )


def _require_completed_publication(
    session: Session,
    command: CompositeMaterializationCommand,
    outcomes: list[CompositeMemberMaterializationOutcome],
    *,
    tenant_id: str,
) -> None:
    publication = _find_member_return_fact_publication(
        session,
        tenant_id=tenant_id,
        composite_id=command.composite_id,
        return_view=command.return_view,
        reporting_currency=command.reporting_currency,
        restatement_sequence=command.restatement_sequence,
    )
    expected = _serialize_fact_families(
        {(item.portfolio_id, command.period_start, command.period_end) for item in outcomes if item.fact is not None}
    )
    if publication is None or (
        publication.period_start,
        publication.period_end,
        publication.source_fingerprint,
        publication.expected_families_json,
    ) != (command.period_start, command.period_end, command.attestation_content_hash, expected):
        raise APIConflictError(
            "Materialization cannot complete without its exact immutable fact publication.",
            error_code="COMPOSITE_MATERIALIZATION_PUBLICATION_REQUIRED",
        )


_store_cache: dict[str, CompositeMaterializationStore] = {}


def get_composite_materialization_store(*, database_url: str | None = None) -> CompositeMaterializationStore:
    return resolve_runtime_store(cache=_store_cache, factory=CompositeMaterializationStore, database_url=database_url)


composite_materialization_store = RuntimeStoreProxy(get_composite_materialization_store)
