from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Date, Integer, String, Text, UniqueConstraint
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.adapters.composite_schema_policy import (
    CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
    POSTGRES_TENANT_ID_CHECK_SQL,
    SQLITE_POSITIVE_INTEGER_SEQUENCE_CHECK_SQL,
    SQLITE_PUBLICATION_DATE_CHECK_SQL,
    SQLITE_TENANT_ID_CHECK_SQL,
)

POSTGRES_ASCII_CURRENCY_CHECK_SQL = (
    "length(reporting_currency) = 3 "
    "AND ascii(substr(reporting_currency, 1, 1)) >= 65 "
    "AND ascii(substr(reporting_currency, 1, 1)) <= 90 "
    "AND ascii(substr(reporting_currency, 2, 1)) >= 65 "
    "AND ascii(substr(reporting_currency, 2, 1)) <= 90 "
    "AND ascii(substr(reporting_currency, 3, 1)) >= 65 "
    "AND ascii(substr(reporting_currency, 3, 1)) <= 90"
)


class MaterializationBase(DeclarativeBase):
    pass


def create_materialization_schema(connection: Connection) -> None:
    # Keep dialect-conditional constraints on their original metadata. Copying
    # this table with to_metadata() loses SQLAlchemy's conditional DDL rules.
    MaterializationBase.metadata.create_all(connection)


class CompositeMaterializationModel(MaterializationBase):
    """One immutable financial scope, with optimistic resumable progress."""

    __tablename__ = "composite_materializations"
    __table_args__ = (
        CheckConstraint(SQLITE_TENANT_ID_CHECK_SQL, name="ck_composite_materialization_tenant").ddl_if(
            dialect="sqlite"
        ),
        CheckConstraint(POSTGRES_TENANT_ID_CHECK_SQL, name="ck_composite_materialization_tenant").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint(CANONICAL_REPORTING_CURRENCY_CHECK_SQL, name="ck_composite_materialization_currency").ddl_if(
            dialect="sqlite"
        ),
        # Text ranges depend on database collation; ASCII codepoints do not.
        CheckConstraint(POSTGRES_ASCII_CURRENCY_CHECK_SQL, name="ck_composite_materialization_currency").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint("return_view IN ('GROSS', 'NET_ACTUAL')", name="ck_composite_materialization_view"),
        CheckConstraint(
            SQLITE_POSITIVE_INTEGER_SEQUENCE_CHECK_SQL, name="ck_composite_materialization_integer_sequence"
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(SQLITE_PUBLICATION_DATE_CHECK_SQL, name="ck_composite_materialization_dates").ddl_if(
            dialect="sqlite"
        ),
        UniqueConstraint(
            "tenant_id",
            "composite_id",
            "return_view",
            "reporting_currency",
            "restatement_sequence",
            name="uq_composite_materialization_financial_scope",
        ),
        CheckConstraint("restatement_sequence >= 1", name="ck_composite_materialization_sequence"),
        CheckConstraint("revision >= 0", name="ck_composite_materialization_revision"),
        CheckConstraint(
            "state IN ('WAITING', 'PUBLISHING', 'COMPLETE', 'BLOCKED')", name="ck_composite_materialization_state"
        ),
        CheckConstraint(
            "period_start >= '0001-01-01' AND period_end <= '9999-12-31' AND period_end >= period_start",
            name="ck_composite_materialization_window",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    materialization_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    composite_id: Mapped[str] = mapped_column(String(128), nullable=False)
    return_view: Mapped[str] = mapped_column(String(32), nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    restatement_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    command_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcomes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="WAITING")
    reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
