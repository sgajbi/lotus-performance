from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date as dt_date
from typing import Iterator

from sqlalchemy import Date, Index, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.models.composites import CompositeDefinition, CompositeMemberReturnFact, CompositeMembership
from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store


class Base(DeclarativeBase):
    pass


class CompositeDefinitionModel(Base):
    __tablename__ = "composite_definitions"

    composite_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    strategy_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    inception_date: Mapped[dt_date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[dt_date | None] = mapped_column(Date, nullable=True)
    calculation_method: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authority_json: Mapped[str] = mapped_column(Text, nullable=False)


class CompositeMembershipModel(Base):
    __tablename__ = "composite_memberships"
    __table_args__ = (
        Index("ix_composite_memberships_composite_effective", "composite_id", "effective_from", "effective_to"),
        Index("ix_composite_memberships_portfolio_effective", "portfolio_id", "effective_from", "effective_to"),
    )

    membership_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    composite_id: Mapped[str] = mapped_column(String(128), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String(128), nullable=False)
    effective_from: Mapped[dt_date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[dt_date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    discretionary: Mapped[str] = mapped_column(String(5), nullable=False)
    source_snapshot_id: Mapped[str] = mapped_column(String(256), nullable=False)


class CompositeMemberReturnFactModel(Base):
    __tablename__ = "composite_member_return_facts"
    __table_args__ = (
        Index("ix_composite_member_return_facts_composite_period", "composite_id", "period_start", "period_end"),
        Index("ix_composite_member_return_facts_portfolio_period", "portfolio_id", "period_start", "period_end"),
        Index("ix_composite_member_return_facts_status", "status"),
    )

    fact_key: Mapped[str] = mapped_column(String(360), primary_key=True)
    composite_id: Mapped[str] = mapped_column(String(128), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String(128), nullable=False)
    period_start: Mapped[dt_date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt_date] = mapped_column(Date, nullable=False)
    return_value: Mapped[str] = mapped_column(Text, nullable=False)
    beginning_market_value: Mapped[str] = mapped_column(Text, nullable=False)
    ending_market_value: Mapped[str] = mapped_column(Text, nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    calculation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot_id: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False)


@dataclass(frozen=True)
class CompositeMetadataCounts:
    definitions: int
    memberships: int
    member_return_facts: int


def _membership_key(membership: CompositeMembership) -> str:
    effective_to = membership.effective_to.isoformat() if membership.effective_to else "open"
    return f"{membership.composite_id}|{membership.portfolio_id}|{membership.effective_from.isoformat()}|{effective_to}"


def _fact_key(fact: CompositeMemberReturnFact) -> str:
    return f"{fact.composite_id}|{fact.portfolio_id}|{fact.period_start.isoformat()}|{fact.period_end.isoformat()}"


class CompositeMetadataStore:
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
            session.query(CompositeMemberReturnFactModel).delete()
            session.query(CompositeMembershipModel).delete()
            session.query(CompositeDefinitionModel).delete()

    def upsert_definition(self, definition: CompositeDefinition) -> None:
        with self._session() as session:
            session.merge(
                CompositeDefinitionModel(
                    composite_id=definition.composite_id,
                    display_name=definition.display_name,
                    strategy_code=definition.strategy_code,
                    reporting_currency=definition.reporting_currency,
                    inception_date=definition.inception_date,
                    termination_date=definition.termination_date,
                    calculation_method=definition.calculation_method.value,
                    source_authority_json=definition.source_authority.model_dump_json(),
                )
            )

    def get_definition(self, composite_id: str) -> CompositeDefinition | None:
        with self._session() as session:
            row = session.get(CompositeDefinitionModel, composite_id)
            if row is None:
                return None
            return CompositeDefinition.model_validate(
                {
                    "composite_id": row.composite_id,
                    "display_name": row.display_name,
                    "strategy_code": row.strategy_code,
                    "reporting_currency": row.reporting_currency,
                    "inception_date": row.inception_date,
                    "termination_date": row.termination_date,
                    "calculation_method": row.calculation_method,
                    "source_authority": json.loads(row.source_authority_json),
                }
            )

    def upsert_membership(self, membership: CompositeMembership) -> None:
        with self._session() as session:
            session.merge(
                CompositeMembershipModel(
                    membership_key=_membership_key(membership),
                    composite_id=membership.composite_id,
                    portfolio_id=membership.portfolio_id,
                    effective_from=membership.effective_from,
                    effective_to=membership.effective_to,
                    status=membership.status.value,
                    status_reason=membership.status_reason,
                    discretionary=str(membership.discretionary).lower(),
                    source_snapshot_id=membership.source_snapshot_id,
                )
            )

    def list_memberships(self, composite_id: str) -> list[CompositeMembership]:
        with self._session() as session:
            statement = (
                select(CompositeMembershipModel)
                .where(CompositeMembershipModel.composite_id == composite_id)
                .order_by(CompositeMembershipModel.effective_from, CompositeMembershipModel.portfolio_id)
            )
            rows = session.execute(statement).scalars().all()
            return [
                CompositeMembership.model_validate(
                    {
                        "composite_id": row.composite_id,
                        "portfolio_id": row.portfolio_id,
                        "effective_from": row.effective_from,
                        "effective_to": row.effective_to,
                        "status": row.status,
                        "status_reason": row.status_reason,
                        "discretionary": row.discretionary == "true",
                        "source_snapshot_id": row.source_snapshot_id,
                    }
                )
                for row in rows
            ]

    def upsert_member_return_fact(self, fact: CompositeMemberReturnFact) -> None:
        with self._session() as session:
            session.merge(
                CompositeMemberReturnFactModel(
                    fact_key=_fact_key(fact),
                    composite_id=fact.composite_id,
                    portfolio_id=fact.portfolio_id,
                    period_start=fact.period_start,
                    period_end=fact.period_end,
                    return_value=str(fact.return_value),
                    beginning_market_value=str(fact.beginning_market_value),
                    ending_market_value=str(fact.ending_market_value),
                    reporting_currency=fact.reporting_currency,
                    calculation_id=fact.calculation_id,
                    source_snapshot_id=fact.source_snapshot_id,
                    status=fact.status.value,
                    reason_codes_json=json.dumps(fact.reason_codes, sort_keys=True),
                )
            )

    def list_member_return_facts(
        self,
        *,
        composite_id: str,
        period_start: dt_date,
        period_end: dt_date,
    ) -> list[CompositeMemberReturnFact]:
        with self._session() as session:
            statement = (
                select(CompositeMemberReturnFactModel)
                .where(
                    CompositeMemberReturnFactModel.composite_id == composite_id,
                    CompositeMemberReturnFactModel.period_start >= period_start,
                    CompositeMemberReturnFactModel.period_end <= period_end,
                )
                .order_by(
                    CompositeMemberReturnFactModel.period_start,
                    CompositeMemberReturnFactModel.period_end,
                    CompositeMemberReturnFactModel.portfolio_id,
                )
            )
            rows = session.execute(statement).scalars().all()
            return [
                CompositeMemberReturnFact.model_validate(
                    {
                        "composite_id": row.composite_id,
                        "portfolio_id": row.portfolio_id,
                        "period_start": row.period_start,
                        "period_end": row.period_end,
                        "return_value": str(row.return_value),
                        "beginning_market_value": str(row.beginning_market_value),
                        "ending_market_value": str(row.ending_market_value),
                        "reporting_currency": row.reporting_currency,
                        "calculation_id": row.calculation_id,
                        "source_snapshot_id": row.source_snapshot_id,
                        "status": row.status,
                        "reason_codes": json.loads(row.reason_codes_json),
                    }
                )
                for row in rows
            ]

    def count_records(self) -> CompositeMetadataCounts:
        with self._session() as session:
            return CompositeMetadataCounts(
                definitions=session.query(CompositeDefinitionModel).count(),
                memberships=session.query(CompositeMembershipModel).count(),
                member_return_facts=session.query(CompositeMemberReturnFactModel).count(),
            )


_store_cache: dict[str, CompositeMetadataStore] = {}


def get_composite_metadata_store(*, database_url: str | None = None) -> CompositeMetadataStore:
    return resolve_runtime_store(cache=_store_cache, factory=CompositeMetadataStore, database_url=database_url)


composite_metadata_store = RuntimeStoreProxy(get_composite_metadata_store)
