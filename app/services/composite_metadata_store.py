from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date as dt_date
from hashlib import sha256
from typing import Any, Iterator

from sqlalchemy import CheckConstraint, Date, Index, String, Text, and_, cast, func, inspect, literal, or_, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.schema import AddConstraint

from app.models.composites import (
    CompositeDefinition,
    CompositeMemberReturnFact,
    CompositeMembership,
    CompositeReturnView,
)
from app.services.durable_database_engine import create_durable_database_engine
from app.services.durable_schema_creation import create_durable_schema
from app.services.durable_store_json import load_json_object_or_none, load_json_string_list_or_default
from app.services.durable_store_runtime import RuntimeStoreProxy, resolve_runtime_store

logger = logging.getLogger(__name__)

INVALID_COMPOSITE_REASON_CODES_PAYLOAD = "invalid_reason_codes_payload"
COMPOSITE_DEFINITION_CURRENCY_CHECK = "ck_composite_definitions_reporting_currency_canonical"
MEMBER_RETURN_FACT_CURRENCY_CHECK = "ck_composite_member_return_facts_reporting_currency_canonical"
MEMBER_RETURN_FACT_SEQUENCE_CHECK = "ck_composite_member_return_facts_restatement_sequence_positive"
MEMBER_RETURN_FACT_SQLITE_SEQUENCE_TYPE_CHECK = "ck_composite_member_return_facts_restatement_sequence_sqlite_integer"
MEMBER_RETURN_FACT_VERSION_CHECK = "ck_composite_member_return_facts_restatement_version_nonblank"
MEMBER_RETURN_FACT_IMMUTABLE_UPDATE_TRIGGER = "trg_composite_member_return_facts_immutable_update"
MEMBER_RETURN_FACT_COMPLETED_DELETE_TRIGGER = "trg_composite_member_return_facts_completed_delete"
PYTHON_STRIP_WHITESPACE_CODEPOINTS = (
    9,
    10,
    11,
    12,
    13,
    28,
    29,
    30,
    31,
    32,
    133,
    160,
    5760,
    8192,
    8193,
    8194,
    8195,
    8196,
    8197,
    8198,
    8199,
    8200,
    8201,
    8202,
    8232,
    8233,
    8239,
    8287,
    12288,
)
POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_SQL = (
    "length(btrim(restatement_version, "
    + " || ".join(f"chr({codepoint})" for codepoint in PYTHON_STRIP_WHITESPACE_CODEPOINTS)
    + ")) > 0"
)
POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_MARKER = "chr(12288)"
SQLITE_MEMBER_RETURN_FACT_VERSION_CHECK_SQL = (
    "length(restatement_version) BETWEEN 1 AND 64 AND length(trim(restatement_version, "
    + " || ".join(f"char({codepoint})" for codepoint in PYTHON_STRIP_WHITESPACE_CODEPOINTS)
    + ")) > 0"
)
PUBLICATION_CURRENCY_CHECK = "ck_composite_fact_publications_reporting_currency_canonical"
PUBLICATION_SEQUENCE_CHECK = "ck_composite_fact_publications_restatement_sequence_positive"
PUBLICATION_SQLITE_SEQUENCE_TYPE_CHECK = "ck_composite_fact_publications_restatement_sequence_sqlite_integer"
PUBLICATION_PERIOD_CHECK = "ck_composite_fact_publications_period_valid"
PUBLICATION_SQLITE_DATE_CHECK = "ck_composite_fact_publications_period_sqlite_dates"
PUBLICATION_IMMUTABLE_UPDATE_TRIGGER = "trg_composite_fact_publications_immutable_update"
SQLITE_POSITIVE_INTEGER_SEQUENCE_CHECK_SQL = "typeof(restatement_sequence) = 'integer' AND restatement_sequence >= 1"
SQLITE_PUBLICATION_DATE_CHECK_SQL = (
    "typeof(period_start) = 'text' "
    "AND length(period_start) = 10 "
    "AND period_start GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "
    "AND substr(period_start, 1, 4) BETWEEN '0001' AND '9999' "
    "AND julianday(period_start) IS NOT NULL "
    "AND date(julianday(period_start)) = period_start "
    "AND typeof(period_end) = 'text' "
    "AND length(period_end) = 10 "
    "AND period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "
    "AND substr(period_end, 1, 4) BETWEEN '0001' AND '9999' "
    "AND julianday(period_end) IS NOT NULL "
    "AND date(julianday(period_end)) = period_end"
)
CANONICAL_REPORTING_CURRENCY_CHECK_SQL = (
    "length(reporting_currency) = 3 "
    "AND reporting_currency = upper(reporting_currency) "
    "AND substr(reporting_currency, 1, 1) BETWEEN 'A' AND 'Z' "
    "AND substr(reporting_currency, 2, 1) BETWEEN 'A' AND 'Z' "
    "AND substr(reporting_currency, 3, 1) BETWEEN 'A' AND 'Z'"
)
MEMBER_RETURN_FACT_SCHEMA_UPGRADE_COLUMNS = {
    "return_view": "TEXT NOT NULL DEFAULT 'NET_ACTUAL'",
    "source_fingerprint": "TEXT NOT NULL DEFAULT 'legacy-source-fingerprint-unavailable'",
    "restatement_version": "VARCHAR(64) NOT NULL DEFAULT 'v1'",
    "restatement_sequence": "INTEGER NOT NULL DEFAULT 1",
}
PUBLICATION_SCHEMA_UPGRADE_COLUMNS = {
    # Pre-scope publication rows implicitly applied to every date. Preserve that
    # compatibility truth when upgrading an early schema rather than inventing a
    # narrower period that cannot be recovered from an empty family manifest.
    "period_start": "DATE NOT NULL DEFAULT '0001-01-01'",
    "period_end": "DATE NOT NULL DEFAULT '9999-12-31'",
}
PUBLICATION_REQUIRED_LINEAGE_COLUMNS = frozenset({"expected_families_json", "source_fingerprint"})


class Base(DeclarativeBase):
    pass


class CompositeDefinitionModel(Base):
    __tablename__ = "composite_definitions"
    __table_args__ = (
        CheckConstraint(
            CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
            name=COMPOSITE_DEFINITION_CURRENCY_CHECK,
        ),
    )

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
        CheckConstraint(
            CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
            name=MEMBER_RETURN_FACT_CURRENCY_CHECK,
        ),
        CheckConstraint("restatement_sequence >= 1", name=MEMBER_RETURN_FACT_SEQUENCE_CHECK),
        CheckConstraint(
            SQLITE_POSITIVE_INTEGER_SEQUENCE_CHECK_SQL,
            name=MEMBER_RETURN_FACT_SQLITE_SEQUENCE_TYPE_CHECK,
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            SQLITE_MEMBER_RETURN_FACT_VERSION_CHECK_SQL,
            name=MEMBER_RETURN_FACT_VERSION_CHECK,
        ).ddl_if(dialect="sqlite"),
        Index("ix_composite_member_return_facts_composite_period", "composite_id", "period_start", "period_end"),
        Index("ix_composite_member_return_facts_portfolio_period", "portfolio_id", "period_start", "period_end"),
        Index("ix_composite_member_return_facts_status", "status"),
        Index(
            "uq_composite_member_return_facts_sequence_identity",
            "composite_id",
            "portfolio_id",
            "period_start",
            "period_end",
            "return_view",
            "reporting_currency",
            "restatement_sequence",
            unique=True,
        ),
        Index(
            "uq_composite_member_return_facts_version_identity",
            "composite_id",
            "portfolio_id",
            "period_start",
            "period_end",
            "return_view",
            "reporting_currency",
            "restatement_version",
            unique=True,
        ),
        Index(
            "ix_composite_member_return_facts_latest_selection",
            "composite_id",
            "return_view",
            "reporting_currency",
            "period_start",
            "period_end",
            "portfolio_id",
            "restatement_sequence",
        ),
    )

    fact_key: Mapped[str] = mapped_column(String(360), primary_key=True)
    composite_id: Mapped[str] = mapped_column(String(128), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String(128), nullable=False)
    period_start: Mapped[dt_date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt_date] = mapped_column(Date, nullable=False)
    return_value: Mapped[str] = mapped_column(Text, nullable=False)
    return_view: Mapped[str] = mapped_column(String(32), nullable=False)
    beginning_market_value: Mapped[str] = mapped_column(Text, nullable=False)
    ending_market_value: Mapped[str] = mapped_column(Text, nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    calculation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(256), nullable=False)
    restatement_version: Mapped[str] = mapped_column(String(64), nullable=False)
    restatement_sequence: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False)


class CompositeMemberReturnFactPublicationModel(Base):
    __tablename__ = "composite_member_return_fact_publications"
    __table_args__ = (
        CheckConstraint(
            CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
            name=PUBLICATION_CURRENCY_CHECK,
        ),
        CheckConstraint(
            "restatement_sequence >= 1",
            name=PUBLICATION_SEQUENCE_CHECK,
        ),
        CheckConstraint(
            SQLITE_POSITIVE_INTEGER_SEQUENCE_CHECK_SQL,
            name=PUBLICATION_SQLITE_SEQUENCE_TYPE_CHECK,
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "period_end >= period_start",
            name=PUBLICATION_PERIOD_CHECK,
        ),
        CheckConstraint(
            SQLITE_PUBLICATION_DATE_CHECK_SQL,
            name=PUBLICATION_SQLITE_DATE_CHECK,
        ).ddl_if(dialect="sqlite"),
        Index(
            "uq_composite_fact_publication_identity",
            "composite_id",
            "return_view",
            "reporting_currency",
            "restatement_sequence",
            unique=True,
        ),
    )

    publication_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    composite_id: Mapped[str] = mapped_column(String(128), nullable=False)
    return_view: Mapped[str] = mapped_column(String(32), nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    restatement_sequence: Mapped[int] = mapped_column(nullable=False)
    period_start: Mapped[dt_date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt_date] = mapped_column(Date, nullable=False)
    expected_families_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(256), nullable=False)


COMPOSITE_CURRENCY_TABLES = (
    CompositeDefinitionModel.__table__,
    CompositeMemberReturnFactModel.__table__,
    CompositeMemberReturnFactPublicationModel.__table__,
)


@dataclass(frozen=True)
class CompositeMetadataCounts:
    definitions: int
    memberships: int
    member_return_facts: int


def _membership_key(membership: CompositeMembership) -> str:
    effective_to = membership.effective_to.isoformat() if membership.effective_to else "open"
    return f"{membership.composite_id}|{membership.portfolio_id}|{membership.effective_from.isoformat()}|{effective_to}"


class CompositeMemberReturnFactConflictError(ValueError):
    """The immutable fact identity already exists with different economics or lineage."""


class CompositeMemberReturnFactSelectionError(ValueError):
    """The explicit selection is absent or the unpinned latest sequence is incomplete."""


def _fact_identity_values(fact: CompositeMemberReturnFact) -> dict[str, str | int]:
    return {
        "composite_id": fact.composite_id,
        "portfolio_id": fact.portfolio_id,
        "period_start": fact.period_start.isoformat(),
        "period_end": fact.period_end.isoformat(),
        "return_view": fact.return_view.value,
        "reporting_currency": fact.reporting_currency,
        "restatement_version": fact.restatement_version,
        "restatement_sequence": fact.restatement_sequence,
    }


def _fact_key(fact: CompositeMemberReturnFact) -> str:
    identity = json.dumps(_fact_identity_values(fact), sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(identity.encode('utf-8')).hexdigest()}"


def _publication_key(
    *,
    composite_id: str,
    return_view: CompositeReturnView,
    reporting_currency: str,
    restatement_sequence: int,
) -> str:
    identity = json.dumps(
        {
            "composite_id": composite_id,
            "reporting_currency": reporting_currency,
            "restatement_sequence": restatement_sequence,
            "return_view": return_view.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{sha256(identity.encode('utf-8')).hexdigest()}"


def _publication_lock_key(publication_key: str) -> int:
    unsigned = int(publication_key.removeprefix("sha256:")[:16], 16)
    return unsigned if unsigned < 2**63 else unsigned - 2**64


def _lock_fact_publication_identity(
    session: Session,
    publication_key: str,
    *,
    exclusive: bool,
) -> None:
    if session.bind is None:
        return
    if session.bind.dialect.name == "sqlite":
        # SQLite has no row or advisory locks. BEGIN IMMEDIATE acquires its single
        # writer reservation before either a fact writer or publication completion
        # observes the family set, preventing a writer from committing between the
        # completion read and immutable manifest insert.
        session.execute(text("BEGIN IMMEDIATE"))
        return
    if session.bind.dialect.name == "postgresql":
        lock_function = func.pg_advisory_xact_lock if exclusive else func.pg_advisory_xact_lock_shared
        session.execute(select(lock_function(_publication_lock_key(publication_key))))


def _serialize_fact_families(families: set[tuple[str, dt_date, dt_date]]) -> str:
    return json.dumps(
        [
            {
                "period_end": period_end.isoformat(),
                "period_start": period_start.isoformat(),
                "portfolio_id": portfolio_id,
            }
            for portfolio_id, period_start, period_end in sorted(families)
        ],
        sort_keys=True,
        separators=(",", ":"),
    )


def _deserialize_fact_families(raw_payload: str) -> set[tuple[str, dt_date, dt_date]]:
    try:
        payload = json.loads(raw_payload)
        if not isinstance(payload, list):
            raise ValueError("publication families must be a list")
        families = {
            (
                str(item["portfolio_id"]),
                dt_date.fromisoformat(str(item["period_start"])),
                dt_date.fromisoformat(str(item["period_end"])),
            )
            for item in payload
            if isinstance(item, dict) and set(item) == {"portfolio_id", "period_start", "period_end"}
        }
        if len(families) != len(payload):
            raise ValueError("publication families contain malformed or duplicate entries")
        return families
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CompositeMemberReturnFactSelectionError(
            "Completed composite fact publication contains malformed family evidence"
        ) from exc


def _row_value(row: Any, field_name: str) -> Any:
    if isinstance(row, dict) or hasattr(row, "keys"):
        return row[field_name]
    return getattr(row, field_name)


def _member_return_fact_from_row(row: Any) -> CompositeMemberReturnFact:
    fact_key = _row_value(row, "fact_key")
    return CompositeMemberReturnFact.model_validate(
        {
            "composite_id": _row_value(row, "composite_id"),
            "portfolio_id": _row_value(row, "portfolio_id"),
            "period_start": _row_value(row, "period_start"),
            "period_end": _row_value(row, "period_end"),
            "return_value": str(_row_value(row, "return_value")),
            "return_view": _row_value(row, "return_view"),
            "beginning_market_value": str(_row_value(row, "beginning_market_value")),
            "ending_market_value": str(_row_value(row, "ending_market_value")),
            "reporting_currency": _row_value(row, "reporting_currency"),
            "calculation_id": _row_value(row, "calculation_id"),
            "source_snapshot_id": _row_value(row, "source_snapshot_id"),
            "source_fingerprint": _row_value(row, "source_fingerprint"),
            "restatement_version": _row_value(row, "restatement_version"),
            "restatement_sequence": _row_value(row, "restatement_sequence"),
            "status": _row_value(row, "status"),
            "reason_codes": _load_reason_codes(
                _row_value(row, "reason_codes_json"),
                row_identifier=fact_key,
            ),
        }
    )


def _member_return_fact_model(fact: CompositeMemberReturnFact) -> CompositeMemberReturnFactModel:
    return CompositeMemberReturnFactModel(
        fact_key=_fact_key(fact),
        composite_id=fact.composite_id,
        portfolio_id=fact.portfolio_id,
        period_start=fact.period_start,
        period_end=fact.period_end,
        return_value=str(fact.return_value),
        return_view=fact.return_view.value,
        beginning_market_value=str(fact.beginning_market_value),
        ending_market_value=str(fact.ending_market_value),
        reporting_currency=fact.reporting_currency,
        calculation_id=fact.calculation_id,
        source_snapshot_id=fact.source_snapshot_id,
        source_fingerprint=fact.source_fingerprint,
        restatement_version=fact.restatement_version,
        restatement_sequence=fact.restatement_sequence,
        status=fact.status.value,
        reason_codes_json=json.dumps(fact.reason_codes, sort_keys=True),
    )


def _find_member_return_fact_identity_collision(
    session: Session,
    fact: CompositeMemberReturnFact,
) -> CompositeMemberReturnFactModel | None:
    statement = select(CompositeMemberReturnFactModel).where(
        CompositeMemberReturnFactModel.composite_id == fact.composite_id,
        CompositeMemberReturnFactModel.portfolio_id == fact.portfolio_id,
        CompositeMemberReturnFactModel.period_start == fact.period_start,
        CompositeMemberReturnFactModel.period_end == fact.period_end,
        CompositeMemberReturnFactModel.return_view == fact.return_view.value,
        CompositeMemberReturnFactModel.reporting_currency == fact.reporting_currency,
        or_(
            CompositeMemberReturnFactModel.restatement_sequence == fact.restatement_sequence,
            CompositeMemberReturnFactModel.restatement_version == fact.restatement_version,
        ),
    )
    return session.execute(statement).scalars().first()


def _accept_idempotent_fact_or_raise_conflict(
    stored_row: CompositeMemberReturnFactModel,
    fact: CompositeMemberReturnFact,
) -> None:
    if _member_return_fact_from_row(stored_row) == fact:
        return
    raise CompositeMemberReturnFactConflictError(
        "Immutable composite member-return fact identity already exists with different payload: "
        f"composite_id={fact.composite_id}, portfolio_id={fact.portfolio_id}, "
        f"period={fact.period_start.isoformat()}..{fact.period_end.isoformat()}, "
        f"return_view={fact.return_view.value}, reporting_currency={fact.reporting_currency}, "
        f"restatement_version={fact.restatement_version}, "
        f"restatement_sequence={fact.restatement_sequence}"
    )


def _add_missing_member_return_fact_columns(connection: Connection, existing_columns: set[str]) -> None:
    missing_columns = _missing_member_return_fact_schema_upgrade_columns(existing_columns)
    for column_name, column_definition in missing_columns.items():
        if connection.dialect.name == "postgresql":
            statement = (
                f"ALTER TABLE composite_member_return_facts ADD COLUMN IF NOT EXISTS {column_name} {column_definition}"
            )
        else:
            statement = f"ALTER TABLE composite_member_return_facts ADD COLUMN {column_name} {column_definition}"
        connection.execute(text(statement))


def _canonical_reporting_currency_predicate(currency_column: Any) -> Any:
    return and_(
        func.length(currency_column) == 3,
        currency_column == func.upper(currency_column),
        func.substr(currency_column, 1, 1).between("A", "Z"),
        func.substr(currency_column, 2, 1).between("A", "Z"),
        func.substr(currency_column, 3, 1).between("A", "Z"),
    )


def _ascii_legacy_currency_predicate(connection: Connection, currency_column: Any) -> Any:
    if connection.dialect.name == "postgresql":
        return currency_column.op("~")(r"^[A-Za-z]{3}$")
    return currency_column.op("GLOB")("[A-Za-z][A-Za-z][A-Za-z]")


def _canonicalize_legacy_composite_currencies(connection: Connection) -> None:
    for table in COMPOSITE_CURRENCY_TABLES:
        currency_column = table.c.reporting_currency
        connection.execute(
            table.update()
            .where(
                _ascii_legacy_currency_predicate(connection, currency_column),
                currency_column != func.upper(currency_column),
            )
            .values(reporting_currency=func.upper(currency_column))
        )


def _reject_invalid_legacy_composite_currencies(connection: Connection) -> None:
    for table in COMPOSITE_CURRENCY_TABLES:
        currency_column = table.c.reporting_currency
        invalid_currency_count = connection.scalar(
            select(func.count())
            .select_from(table)
            .where(
                or_(
                    currency_column.is_(None),
                    ~_canonical_reporting_currency_predicate(currency_column),
                )
            )
        )
        if invalid_currency_count:
            raise RuntimeError(
                "Composite metadata upgrade found "
                f"{invalid_currency_count} row(s) with invalid reporting_currency "
                f"in {table.name}; currencies must be three uppercase ASCII letters"
            )


def _upgrade_legacy_composite_currencies(connection: Connection) -> None:
    _canonicalize_legacy_composite_currencies(connection)
    _reject_invalid_legacy_composite_currencies(connection)


def _reject_invalid_member_return_fact_versions(connection: Connection) -> None:
    version_column = CompositeMemberReturnFactModel.__table__.c.restatement_version
    invalid_version_count = sum(
        1
        for version in connection.scalars(select(version_column))
        if not isinstance(version, str) or not version.strip() or len(version) > 64
    )
    if invalid_version_count:
        raise RuntimeError(
            "Composite member-return fact upgrade found "
            f"{invalid_version_count} row(s) with invalid restatement_version; "
            "labels must be nonblank and at most 64 characters"
        )


def _reject_invalid_positive_integer_sequences(
    connection: Connection,
    *,
    table: Any,
    owner_description: str,
) -> None:
    sequence_column = table.c.restatement_sequence
    invalid_predicate = or_(sequence_column.is_(None), sequence_column < 1)
    if connection.dialect.name == "sqlite":
        invalid_predicate = or_(
            invalid_predicate,
            func.typeof(sequence_column) != "integer",
        )
    invalid_sequence_count = connection.scalar(select(func.count()).select_from(table).where(invalid_predicate))
    if invalid_sequence_count:
        raise RuntimeError(
            f"{owner_description} upgrade found "
            f"{invalid_sequence_count} row(s) with invalid restatement_sequence; "
            "sequences must be positive integers"
        )


def _reject_invalid_member_return_fact_sequences(connection: Connection) -> None:
    _reject_invalid_positive_integer_sequences(
        connection,
        table=CompositeMemberReturnFactModel.__table__,
        owner_description="Composite member-return fact",
    )


def _reject_invalid_publication_sequences(connection: Connection) -> None:
    _reject_invalid_positive_integer_sequences(
        connection,
        table=CompositeMemberReturnFactPublicationModel.__table__,
        owner_description="Composite member-return fact publication",
    )


def _publication_period_storage_type_expressions(connection: Connection, table: Any) -> tuple[Any, Any]:
    if connection.dialect.name == "sqlite":
        return func.typeof(table.c.period_start), func.typeof(table.c.period_end)
    return literal("text"), literal("text")


def _publication_period_is_invalid(
    period_start_type: str,
    raw_period_start: str,
    period_end_type: str,
    raw_period_end: str,
) -> bool:
    if period_start_type != "text" or period_end_type != "text":
        return True
    try:
        period_start = dt_date.fromisoformat(raw_period_start)
        period_end = dt_date.fromisoformat(raw_period_end)
    except (TypeError, ValueError):
        return True
    return (
        raw_period_start != period_start.isoformat()
        or raw_period_end != period_end.isoformat()
        or period_end < period_start
    )


def _reject_invalid_publication_periods(connection: Connection) -> None:
    table = CompositeMemberReturnFactPublicationModel.__table__
    period_start_storage_type, period_end_storage_type = _publication_period_storage_type_expressions(connection, table)
    retained_periods = connection.execute(
        select(
            period_start_storage_type,
            cast(table.c.period_start, String),
            period_end_storage_type,
            cast(table.c.period_end, String),
        )
    )
    invalid_period_count = 0
    for period_start_type, raw_period_start, period_end_type, raw_period_end in retained_periods:
        if _publication_period_is_invalid(
            period_start_type,
            raw_period_start,
            period_end_type,
            raw_period_end,
        ):
            invalid_period_count += 1
    if invalid_period_count:
        raise RuntimeError(
            "Composite member-return fact publication upgrade found "
            f"{invalid_period_count} row(s) with an invalid publication period; "
            "period_start and period_end must be canonical YYYY-MM-DD dates and period_end must not precede period_start"
        )


def _drop_stale_postgres_member_return_fact_version_check(
    connection: Connection,
    check_constraints: dict[str, str],
) -> None:
    installed_definition = check_constraints.get(MEMBER_RETURN_FACT_VERSION_CHECK)
    if installed_definition is None or POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_MARKER in installed_definition:
        return
    connection.execute(
        text(f"ALTER TABLE composite_member_return_facts DROP CONSTRAINT {MEMBER_RETURN_FACT_VERSION_CHECK}")
    )
    check_constraints.pop(MEMBER_RETURN_FACT_VERSION_CHECK)


def _add_missing_postgres_member_return_fact_checks(
    connection: Connection,
    check_constraints: dict[str, str],
) -> None:
    constraint_definitions = {
        MEMBER_RETURN_FACT_CURRENCY_CHECK: CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
        MEMBER_RETURN_FACT_SEQUENCE_CHECK: "restatement_sequence >= 1",
        MEMBER_RETURN_FACT_VERSION_CHECK: POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_SQL,
    }
    for constraint_name, definition in constraint_definitions.items():
        if constraint_name not in check_constraints:
            connection.execute(
                text(f"ALTER TABLE composite_member_return_facts ADD CONSTRAINT {constraint_name} CHECK ({definition})")
            )


def _upgrade_postgres_member_return_fact_constraints(connection: Connection) -> None:
    columns_by_name = {
        column["name"]: column for column in inspect(connection).get_columns("composite_member_return_facts")
    }
    version_column = columns_by_name["restatement_version"]
    if getattr(version_column["type"], "length", None) != 64:
        connection.execute(
            text("ALTER TABLE composite_member_return_facts ALTER COLUMN restatement_version TYPE VARCHAR(64)")
        )
    if version_column["nullable"]:
        connection.execute(
            text("ALTER TABLE composite_member_return_facts ALTER COLUMN restatement_version SET NOT NULL")
        )
    if columns_by_name["restatement_sequence"]["default"] is None:
        connection.execute(
            text("ALTER TABLE composite_member_return_facts ALTER COLUMN restatement_sequence SET DEFAULT 1")
        )
    if columns_by_name["restatement_sequence"]["nullable"]:
        connection.execute(
            text("ALTER TABLE composite_member_return_facts ALTER COLUMN restatement_sequence SET NOT NULL")
        )
    check_constraints = {
        constraint["name"]: constraint.get("sqltext") or ""
        for constraint in inspect(connection).get_check_constraints("composite_member_return_facts")
    }
    _drop_stale_postgres_member_return_fact_version_check(connection, check_constraints)
    _add_missing_postgres_member_return_fact_checks(connection, check_constraints)


def _create_member_return_fact_indexes(connection: Connection) -> None:
    for index in CompositeMemberReturnFactModel.__table__.indexes:
        index.create(connection, checkfirst=True)


def _add_missing_publication_columns(connection: Connection) -> None:
    existing_columns = {
        column["name"]
        for column in inspect(connection).get_columns(CompositeMemberReturnFactPublicationModel.__tablename__)
    }
    for column_name, column_definition in PUBLICATION_SCHEMA_UPGRADE_COLUMNS.items():
        if column_name in existing_columns:
            continue
        if connection.dialect.name == "postgresql":
            statement = (
                "ALTER TABLE composite_member_return_fact_publications "
                f"ADD COLUMN IF NOT EXISTS {column_name} {column_definition}"
            )
        else:
            statement = (
                f"ALTER TABLE composite_member_return_fact_publications ADD COLUMN {column_name} {column_definition}"
            )
        connection.execute(text(statement))


def _require_publication_lineage_columns(connection: Connection) -> None:
    existing_columns = {
        column["name"]
        for column in inspect(connection).get_columns(CompositeMemberReturnFactPublicationModel.__tablename__)
    }
    missing_columns = sorted(PUBLICATION_REQUIRED_LINEAGE_COLUMNS - existing_columns)
    if missing_columns:
        raise RuntimeError(
            "Composite fact publication schema is missing required lineage column(s): "
            f"{', '.join(missing_columns)}. Apply the governed migration; bootstrap cannot invent lineage authority."
        )


def _make_postgres_publication_columns_non_nullable(
    connection: Connection,
    columns_by_name: dict[str, Any],
) -> None:
    statements = (
        (
            "restatement_sequence",
            "ALTER TABLE composite_member_return_fact_publications ALTER COLUMN restatement_sequence SET NOT NULL",
        ),
        (
            "reporting_currency",
            "ALTER TABLE composite_member_return_fact_publications ALTER COLUMN reporting_currency SET NOT NULL",
        ),
        (
            "period_start",
            "ALTER TABLE composite_member_return_fact_publications ALTER COLUMN period_start SET NOT NULL",
        ),
        (
            "period_end",
            "ALTER TABLE composite_member_return_fact_publications ALTER COLUMN period_end SET NOT NULL",
        ),
    )
    for column_name, statement in statements:
        if columns_by_name[column_name]["nullable"]:
            connection.execute(text(statement))


def _upgrade_postgres_publication_constraints(connection: Connection) -> None:
    columns_by_name = {
        column["name"]: column
        for column in inspect(connection).get_columns(CompositeMemberReturnFactPublicationModel.__tablename__)
    }
    _make_postgres_publication_columns_non_nullable(connection, columns_by_name)
    constraint_names = {
        constraint["name"]
        for constraint in inspect(connection).get_check_constraints(
            CompositeMemberReturnFactPublicationModel.__tablename__
        )
    }
    constraint_definitions = {
        PUBLICATION_CURRENCY_CHECK: CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
        PUBLICATION_SEQUENCE_CHECK: "restatement_sequence >= 1",
        PUBLICATION_PERIOD_CHECK: "period_end >= period_start",
    }
    for constraint_name, definition in constraint_definitions.items():
        if constraint_name not in constraint_names:
            connection.execute(
                text(
                    "ALTER TABLE composite_member_return_fact_publications "
                    f"ADD CONSTRAINT {constraint_name} CHECK ({definition})"
                )
            )


def _upgrade_publication_schema(connection: Connection) -> None:
    _require_publication_lineage_columns(connection)
    _add_missing_publication_columns(connection)
    _reject_invalid_publication_sequences(connection)
    _reject_invalid_publication_periods(connection)
    if connection.dialect.name == "postgresql":
        _upgrade_postgres_publication_constraints(connection)
    for index in CompositeMemberReturnFactPublicationModel.__table__.indexes:
        index.create(connection, checkfirst=True)


def _upgrade_postgres_definition_currency_constraint(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    table_name = CompositeDefinitionModel.__tablename__
    columns_by_name = {column["name"]: column for column in inspect(connection).get_columns(table_name)}
    if columns_by_name["reporting_currency"]["nullable"]:
        connection.execute(text("ALTER TABLE composite_definitions ALTER COLUMN reporting_currency SET NOT NULL"))
    constraint_names = {constraint["name"] for constraint in inspect(connection).get_check_constraints(table_name)}
    if COMPOSITE_DEFINITION_CURRENCY_CHECK not in constraint_names:
        definition_constraint = next(
            constraint
            for constraint in CompositeDefinitionModel.__table__.constraints
            if constraint.name == COMPOSITE_DEFINITION_CURRENCY_CHECK
        )
        connection.execute(AddConstraint(definition_constraint))


def _create_sqlite_composite_fact_validation_guards(connection: Connection) -> None:
    if connection.dialect.name != "sqlite":
        raise RuntimeError("SQLite composite-fact validation guards require a SQLite connection")
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_member_return_facts_validate_insert")
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_fact_publications_validate_insert")
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_member_return_facts_validate_insert
        BEFORE INSERT ON composite_member_return_facts
        WHEN typeof(NEW.reporting_currency) != 'text'
          OR length(NEW.reporting_currency) != 3
          OR NEW.reporting_currency != upper(NEW.reporting_currency)
          OR substr(NEW.reporting_currency, 1, 1) NOT BETWEEN 'A' AND 'Z'
          OR substr(NEW.reporting_currency, 2, 1) NOT BETWEEN 'A' AND 'Z'
          OR substr(NEW.reporting_currency, 3, 1) NOT BETWEEN 'A' AND 'Z'
          OR typeof(NEW.restatement_version) != 'text'
          OR length(NEW.restatement_version) NOT BETWEEN 1 AND 64
          OR length(trim(NEW.restatement_version,
              char(9) || char(10) || char(11) || char(12) || char(13) ||
              char(28) || char(29) || char(30) || char(31) || char(32) ||
              char(133) || char(160) || char(5760) || char(8192) || char(8193) ||
              char(8194) || char(8195) || char(8196) || char(8197) || char(8198) ||
              char(8199) || char(8200) || char(8201) || char(8202) || char(8232) ||
              char(8233) || char(8239) || char(8287) || char(12288))) = 0
          OR typeof(NEW.restatement_sequence) != 'integer'
          OR NEW.restatement_sequence < 1
        BEGIN
            SELECT RAISE(ABORT, 'composite member-return fact identity fields are invalid');
        END
        """
    )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_fact_publications_validate_insert
        BEFORE INSERT ON composite_member_return_fact_publications
        WHEN typeof(NEW.reporting_currency) != 'text'
          OR length(NEW.reporting_currency) != 3
          OR NEW.reporting_currency != upper(NEW.reporting_currency)
          OR substr(NEW.reporting_currency, 1, 1) NOT BETWEEN 'A' AND 'Z'
          OR substr(NEW.reporting_currency, 2, 1) NOT BETWEEN 'A' AND 'Z'
          OR substr(NEW.reporting_currency, 3, 1) NOT BETWEEN 'A' AND 'Z'
          OR typeof(NEW.restatement_sequence) != 'integer'
          OR NEW.restatement_sequence < 1
          OR typeof(NEW.period_start) != 'text'
          OR length(NEW.period_start) != 10
          OR NEW.period_start NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
          OR substr(NEW.period_start, 1, 4) NOT BETWEEN '0001' AND '9999'
          OR julianday(NEW.period_start) IS NULL
          OR date(julianday(NEW.period_start)) != NEW.period_start
          OR typeof(NEW.period_end) != 'text'
          OR length(NEW.period_end) != 10
          OR NEW.period_end NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
          OR substr(NEW.period_end, 1, 4) NOT BETWEEN '0001' AND '9999'
          OR julianday(NEW.period_end) IS NULL
          OR date(julianday(NEW.period_end)) != NEW.period_end
          OR NEW.period_end < NEW.period_start
        BEGIN
            SELECT RAISE(ABORT, 'composite fact publication requires a positive integer sequence and valid calendar period');
        END
        """
    )


def _create_sqlite_definition_currency_guards(connection: Connection) -> None:
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_definitions_validate_insert")
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_definitions_validate_update")
    statements = (
        """
        CREATE TRIGGER trg_composite_definitions_validate_insert
        BEFORE INSERT ON composite_definitions
        WHEN typeof(NEW.reporting_currency) != 'text'
          OR length(NEW.reporting_currency) != 3
          OR NEW.reporting_currency != upper(NEW.reporting_currency)
          OR substr(NEW.reporting_currency, 1, 1) NOT BETWEEN 'A' AND 'Z'
          OR substr(NEW.reporting_currency, 2, 1) NOT BETWEEN 'A' AND 'Z'
          OR substr(NEW.reporting_currency, 3, 1) NOT BETWEEN 'A' AND 'Z'
        BEGIN
            SELECT RAISE(ABORT, 'composite definition reporting currency is invalid');
        END
        """,
        """
        CREATE TRIGGER trg_composite_definitions_validate_update
        BEFORE UPDATE OF reporting_currency ON composite_definitions
        WHEN typeof(NEW.reporting_currency) != 'text'
          OR length(NEW.reporting_currency) != 3
          OR NEW.reporting_currency != upper(NEW.reporting_currency)
          OR substr(NEW.reporting_currency, 1, 1) NOT BETWEEN 'A' AND 'Z'
          OR substr(NEW.reporting_currency, 2, 1) NOT BETWEEN 'A' AND 'Z'
          OR substr(NEW.reporting_currency, 3, 1) NOT BETWEEN 'A' AND 'Z'
        BEGIN
            SELECT RAISE(ABORT, 'composite definition reporting currency is invalid');
        END
        """,
    )
    for statement in statements:
        connection.exec_driver_sql(statement)


def _create_sqlite_member_return_fact_immutability_guards(connection: Connection) -> None:
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_member_return_facts_immutable_update")
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_member_return_facts_completed_delete")
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_member_return_facts_immutable_update
        BEFORE UPDATE ON composite_member_return_facts
        BEGIN
            SELECT RAISE(ABORT, 'composite member-return facts are immutable; write a new restatement sequence');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_member_return_facts_completed_delete
        BEFORE DELETE ON composite_member_return_facts
        WHEN EXISTS (
            SELECT 1
            FROM composite_member_return_fact_publications AS publication
            WHERE publication.composite_id = OLD.composite_id
              AND publication.return_view = OLD.return_view
              AND publication.reporting_currency = OLD.reporting_currency
              AND publication.restatement_sequence = OLD.restatement_sequence
        )
        BEGIN
            SELECT RAISE(ABORT, 'completed composite member-return facts cannot be deleted');
        END
        """
    )


def _create_sqlite_publication_immutability_guard(connection: Connection) -> None:
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_fact_publications_immutable_update")
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_fact_publications_immutable_update
        BEFORE UPDATE ON composite_member_return_fact_publications
        BEGIN
            SELECT RAISE(ABORT, 'composite fact publications are immutable; write a new restatement sequence');
        END
        """
    )


def _create_postgres_member_return_fact_immutability_guards(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION reject_composite_member_return_fact_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'composite member-return facts are immutable; write a new restatement sequence';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM composite_member_return_fact_publications AS publication
                WHERE publication.composite_id = OLD.composite_id
                  AND publication.return_view = OLD.return_view
                  AND publication.reporting_currency = OLD.reporting_currency
                  AND publication.restatement_sequence = OLD.restatement_sequence
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'completed composite member-return facts cannot be deleted';
            END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_composite_member_return_facts_immutable_update ON composite_member_return_facts"
    )
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_composite_member_return_facts_completed_delete ON composite_member_return_facts"
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_member_return_facts_immutable_update
        BEFORE UPDATE ON composite_member_return_facts
        FOR EACH ROW
        EXECUTE FUNCTION reject_composite_member_return_fact_mutation()
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_member_return_facts_completed_delete
        BEFORE DELETE ON composite_member_return_facts
        FOR EACH ROW
        EXECUTE FUNCTION reject_composite_member_return_fact_mutation()
        """
    )


def _create_postgres_publication_immutability_guard(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION reject_composite_fact_publication_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION USING
                ERRCODE = '23514',
                MESSAGE = 'composite fact publications are immutable; write a new restatement sequence';
        END;
        $$
        """
    )
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_composite_fact_publications_immutable_update "
        "ON composite_member_return_fact_publications"
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_fact_publications_immutable_update
        BEFORE UPDATE ON composite_member_return_fact_publications
        FOR EACH ROW
        EXECUTE FUNCTION reject_composite_fact_publication_update()
        """
    )


def _create_composite_fact_database_guards(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        _create_sqlite_definition_currency_guards(connection)
        _create_sqlite_composite_fact_validation_guards(connection)
        _create_sqlite_member_return_fact_immutability_guards(connection)
        _create_sqlite_publication_immutability_guard(connection)
    elif connection.dialect.name == "postgresql":
        _create_postgres_member_return_fact_immutability_guards(connection)
        _create_postgres_publication_immutability_guard(connection)


def _resolve_member_return_fact_sequence(
    session: Session,
    *,
    filters: tuple[Any, ...],
    publication_filters: tuple[Any, ...],
    requested_sequence: int | None,
) -> tuple[int | None, bool]:
    if requested_sequence is not None:
        return requested_sequence, False
    latest_fact_sequence = session.scalar(
        select(func.max(CompositeMemberReturnFactModel.restatement_sequence)).where(*filters)
    )
    latest_publication_sequence = session.scalar(
        select(func.max(CompositeMemberReturnFactPublicationModel.restatement_sequence)).where(*publication_filters)
    )
    available_sequences = [
        sequence for sequence in (latest_fact_sequence, latest_publication_sequence) if sequence is not None
    ]
    return (max(available_sequences) if available_sequences else None), True


def _member_return_fact_families(session: Session, *, filters: tuple[Any, ...]) -> set[tuple[str, dt_date, dt_date]]:
    return set(
        session.execute(
            select(
                CompositeMemberReturnFactModel.portfolio_id,
                CompositeMemberReturnFactModel.period_start,
                CompositeMemberReturnFactModel.period_end,
            )
            .where(*filters)
            .distinct()
        ).all()
    )


def _completed_publication_families(
    session: Session,
    *,
    publication_filters: tuple[Any, ...],
    selected_sequence: int,
    period_start: dt_date,
    period_end: dt_date,
) -> set[tuple[str, dt_date, dt_date]] | None:
    publication = session.execute(
        select(CompositeMemberReturnFactPublicationModel).where(
            *publication_filters,
            CompositeMemberReturnFactPublicationModel.restatement_sequence == selected_sequence,
        )
    ).scalar_one_or_none()
    if publication is None:
        return None
    if publication.period_start > period_start or publication.period_end < period_end:
        raise CompositeMemberReturnFactSelectionError(
            "Completed restatement_sequence does not cover the requested window: "
            f"sequence={selected_sequence}, "
            f"publication={publication.period_start.isoformat()}..{publication.period_end.isoformat()}, "
            f"requested={period_start.isoformat()}..{period_end.isoformat()}"
        )
    return {
        family
        for family in _deserialize_fact_families(publication.expected_families_json)
        if family[1] >= period_start and family[2] <= period_end
    }


def _validate_completed_member_return_fact_selection(
    *,
    selected_sequence: int,
    expected_families: set[tuple[str, dt_date, dt_date]],
    selected_rows: list[CompositeMemberReturnFactModel],
) -> None:
    selected_families = {(row.portfolio_id, row.period_start, row.period_end) for row in selected_rows}
    if selected_families != expected_families:
        raise CompositeMemberReturnFactSelectionError(
            "Selected restatement_sequence does not match its completed member-return "
            f"fact universe in the requested window: sequence={selected_sequence}, "
            f"selected={len(selected_families)}, expected={len(expected_families)}"
        )


def _validate_member_return_fact_selection(
    *,
    selecting_latest: bool,
    selected_sequence: int,
    expected_families: set[tuple[str, dt_date, dt_date]],
    has_completed_publication: bool,
    selected_rows: list[CompositeMemberReturnFactModel],
) -> None:
    if selecting_latest and not has_completed_publication:
        raise CompositeMemberReturnFactSelectionError(
            "Latest restatement_sequence has no completed publication manifest in the requested "
            f"window: sequence={selected_sequence}"
        )
    if has_completed_publication:
        _validate_completed_member_return_fact_selection(
            selected_sequence=selected_sequence,
            expected_families=expected_families,
            selected_rows=selected_rows,
        )
        return
    if not selected_rows and not has_completed_publication:
        raise CompositeMemberReturnFactSelectionError(
            f"Explicit restatement_sequence is not retained for the requested fact set: sequence={selected_sequence}"
        )


def _validate_publication_identity_fields(
    *,
    reporting_currency: str,
    restatement_sequence: int,
    source_fingerprint: str,
) -> None:
    if restatement_sequence < 1:
        raise ValueError("restatement_sequence must be positive")
    if not source_fingerprint.strip():
        raise ValueError("source_fingerprint must not be blank")
    if (
        len(reporting_currency) != 3
        or not reporting_currency.isascii()
        or not reporting_currency.isalpha()
        or reporting_currency != reporting_currency.upper()
    ):
        raise ValueError("reporting_currency must be a canonical three-letter code")


def _validate_publication_periods(
    *,
    period_start: dt_date,
    period_end: dt_date,
    expected_families: set[tuple[str, dt_date, dt_date]],
) -> None:
    if period_end < period_start:
        raise ValueError("publication period must be valid")
    if any(family_end < family_start for _, family_start, family_end in expected_families):
        raise ValueError("publication fact-family periods must be valid")
    if any(family_start < period_start or family_end > period_end for _, family_start, family_end in expected_families):
        raise ValueError("publication fact families must fall within its declared period")


def _validate_member_return_fact_publication_request(
    *,
    reporting_currency: str,
    restatement_sequence: int,
    period_start: dt_date,
    period_end: dt_date,
    expected_families: set[tuple[str, dt_date, dt_date]],
    source_fingerprint: str,
) -> None:
    _validate_publication_identity_fields(
        reporting_currency=reporting_currency,
        restatement_sequence=restatement_sequence,
        source_fingerprint=source_fingerprint,
    )
    _validate_publication_periods(
        period_start=period_start,
        period_end=period_end,
        expected_families=expected_families,
    )


def _require_exact_publication_families(
    *,
    actual_families: set[tuple[str, dt_date, dt_date]],
    expected_families: set[tuple[str, dt_date, dt_date]],
    restatement_sequence: int,
) -> None:
    if actual_families != expected_families:
        raise CompositeMemberReturnFactSelectionError(
            "Cannot complete composite fact publication before its exact source-declared "
            f"universe is durable: sequence={restatement_sequence}, "
            f"actual={len(actual_families)}, expected={len(expected_families)}"
        )


def _accept_idempotent_publication_or_raise_conflict(
    existing: CompositeMemberReturnFactPublicationModel,
    *,
    expected_families_json: str,
    source_fingerprint: str,
    period_start: dt_date,
    period_end: dt_date,
    restatement_sequence: int,
) -> None:
    if (
        existing.expected_families_json == expected_families_json
        and existing.source_fingerprint == source_fingerprint
        and existing.period_start == period_start
        and existing.period_end == period_end
    ):
        return
    raise CompositeMemberReturnFactConflictError(
        "Completed composite fact publication identity already exists with different "
        f"universe or lineage: sequence={restatement_sequence}"
    )


def _find_member_return_fact_publication(
    session: Session,
    *,
    composite_id: str,
    return_view: CompositeReturnView,
    reporting_currency: str,
    restatement_sequence: int,
) -> CompositeMemberReturnFactPublicationModel | None:
    """Resolve a publication by its governed identity, independent of a legacy key."""

    return session.execute(
        select(CompositeMemberReturnFactPublicationModel).where(
            CompositeMemberReturnFactPublicationModel.composite_id == composite_id,
            CompositeMemberReturnFactPublicationModel.return_view == return_view.value,
            CompositeMemberReturnFactPublicationModel.reporting_currency == reporting_currency,
            CompositeMemberReturnFactPublicationModel.restatement_sequence == restatement_sequence,
        )
    ).scalar_one_or_none()


class CompositeMetadataStore:
    def __init__(self, database_url: str):
        self._engine = create_durable_database_engine(database_url)
        self._session_factory = sessionmaker(bind=self._engine, future=True)

    def close(self) -> None:
        self._engine.dispose()

    def create_schema(self) -> None:
        create_durable_schema(
            self._engine,
            Base.metadata,
            schema_upgrades=(
                _upgrade_legacy_composite_currencies,
                _upgrade_postgres_definition_currency_constraint,
                self._upgrade_member_return_fact_schema,
                _upgrade_publication_schema,
                _create_composite_fact_database_guards,
            ),
        )

    def _upgrade_member_return_fact_schema(self, connection: Connection) -> None:
        existing_columns = {
            column["name"] for column in inspect(connection).get_columns("composite_member_return_facts")
        }
        _add_missing_member_return_fact_columns(connection, existing_columns)
        _reject_invalid_member_return_fact_sequences(connection)
        _reject_invalid_member_return_fact_versions(connection)
        if connection.dialect.name == "postgresql":
            _upgrade_postgres_member_return_fact_constraints(connection)
        _create_member_return_fact_indexes(connection)

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
            session.query(CompositeMemberReturnFactPublicationModel).delete()
            session.query(CompositeMemberReturnFactModel).delete()
            session.query(CompositeMembershipModel).delete()
            session.query(CompositeDefinitionModel).delete()

    def clear_records_for_composites(self, composite_ids: set[str]) -> None:
        if not composite_ids:
            return
        with self._session() as session:
            session.query(CompositeMemberReturnFactPublicationModel).filter(
                CompositeMemberReturnFactPublicationModel.composite_id.in_(composite_ids)
            ).delete(synchronize_session=False)
            session.query(CompositeMemberReturnFactModel).filter(
                CompositeMemberReturnFactModel.composite_id.in_(composite_ids)
            ).delete(synchronize_session=False)
            session.query(CompositeMembershipModel).filter(
                CompositeMembershipModel.composite_id.in_(composite_ids)
            ).delete(synchronize_session=False)
            session.query(CompositeDefinitionModel).filter(
                CompositeDefinitionModel.composite_id.in_(composite_ids)
            ).delete(synchronize_session=False)

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
            source_authority = _load_json_object(
                row.source_authority_json,
                row_identifier=row.composite_id,
                payload_name="composite source authority",
            )
            if source_authority is None:
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
                    "source_authority": source_authority,
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
        session = self._session_factory()
        try:
            publication_key = _publication_key(
                composite_id=fact.composite_id,
                return_view=fact.return_view,
                reporting_currency=fact.reporting_currency,
                restatement_sequence=fact.restatement_sequence,
            )
            # Writers share the publication fence so independent member facts can
            # proceed concurrently. Publication completion takes the exclusive form,
            # which waits for every admitted writer before attesting the exact set.
            _lock_fact_publication_identity(session, publication_key, exclusive=False)
            collision = _find_member_return_fact_identity_collision(session, fact)
            if collision is not None:
                _accept_idempotent_fact_or_raise_conflict(collision, fact)
                return
            if (
                _find_member_return_fact_publication(
                    session,
                    composite_id=fact.composite_id,
                    return_view=fact.return_view,
                    reporting_currency=fact.reporting_currency,
                    restatement_sequence=fact.restatement_sequence,
                )
                is not None
            ):
                raise CompositeMemberReturnFactConflictError(
                    "Completed composite fact publication is immutable; a new family cannot be "
                    f"added after completion: sequence={fact.restatement_sequence}"
                )
            session.add(_member_return_fact_model(fact))
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            collision = _find_member_return_fact_identity_collision(session, fact)
            if collision is None:
                raise
            try:
                _accept_idempotent_fact_or_raise_conflict(collision, fact)
            except CompositeMemberReturnFactConflictError as conflict:
                raise conflict from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def complete_member_return_fact_publication(
        self,
        *,
        composite_id: str,
        return_view: CompositeReturnView,
        reporting_currency: str,
        restatement_sequence: int,
        period_start: dt_date,
        period_end: dt_date,
        expected_families: set[tuple[str, dt_date, dt_date]],
        source_fingerprint: str,
    ) -> None:
        """Durably attest the exact fact universe for one immutable sequence."""
        _validate_member_return_fact_publication_request(
            reporting_currency=reporting_currency,
            restatement_sequence=restatement_sequence,
            period_start=period_start,
            period_end=period_end,
            expected_families=expected_families,
            source_fingerprint=source_fingerprint,
        )

        publication_key = _publication_key(
            composite_id=composite_id,
            return_view=return_view,
            reporting_currency=reporting_currency,
            restatement_sequence=restatement_sequence,
        )
        expected_families_json = _serialize_fact_families(expected_families)
        with self._session() as session:
            _lock_fact_publication_identity(session, publication_key, exclusive=True)
            actual_families = _member_return_fact_families(
                session,
                filters=(
                    CompositeMemberReturnFactModel.composite_id == composite_id,
                    CompositeMemberReturnFactModel.return_view == return_view.value,
                    CompositeMemberReturnFactModel.reporting_currency == reporting_currency,
                    CompositeMemberReturnFactModel.restatement_sequence == restatement_sequence,
                ),
            )
            _require_exact_publication_families(
                actual_families=actual_families,
                expected_families=expected_families,
                restatement_sequence=restatement_sequence,
            )

            existing = _find_member_return_fact_publication(
                session,
                composite_id=composite_id,
                return_view=return_view,
                reporting_currency=reporting_currency,
                restatement_sequence=restatement_sequence,
            )
            if existing is not None:
                _accept_idempotent_publication_or_raise_conflict(
                    existing,
                    expected_families_json=expected_families_json,
                    source_fingerprint=source_fingerprint,
                    period_start=period_start,
                    period_end=period_end,
                    restatement_sequence=restatement_sequence,
                )
                return
            session.add(
                CompositeMemberReturnFactPublicationModel(
                    publication_key=publication_key,
                    composite_id=composite_id,
                    return_view=return_view.value,
                    reporting_currency=reporting_currency,
                    restatement_sequence=restatement_sequence,
                    period_start=period_start,
                    period_end=period_end,
                    expected_families_json=expected_families_json,
                    source_fingerprint=source_fingerprint,
                )
            )

    def list_member_return_facts(
        self,
        *,
        composite_id: str,
        period_start: dt_date,
        period_end: dt_date,
        return_view: CompositeReturnView,
        reporting_currency: str,
        restatement_sequence: int | None = None,
    ) -> list[CompositeMemberReturnFact]:
        with self._session() as session:
            publication_identity_filters = (
                CompositeMemberReturnFactPublicationModel.composite_id == composite_id,
                CompositeMemberReturnFactPublicationModel.return_view == return_view.value,
                CompositeMemberReturnFactPublicationModel.reporting_currency == reporting_currency,
            )
            covering_publication_filters = (
                *publication_identity_filters,
                CompositeMemberReturnFactPublicationModel.period_start <= period_start,
                CompositeMemberReturnFactPublicationModel.period_end >= period_end,
            )
            filters = (
                CompositeMemberReturnFactModel.composite_id == composite_id,
                CompositeMemberReturnFactModel.period_start >= period_start,
                CompositeMemberReturnFactModel.period_end <= period_end,
                CompositeMemberReturnFactModel.return_view == return_view.value,
                CompositeMemberReturnFactModel.reporting_currency == reporting_currency,
            )
            selected_sequence, selecting_latest = _resolve_member_return_fact_sequence(
                session,
                filters=filters,
                publication_filters=covering_publication_filters,
                requested_sequence=restatement_sequence,
            )
            if selected_sequence is None:
                return []
            statement = select(CompositeMemberReturnFactModel).where(
                *filters,
                CompositeMemberReturnFactModel.restatement_sequence == selected_sequence,
            )
            statement = statement.order_by(
                CompositeMemberReturnFactModel.period_start,
                CompositeMemberReturnFactModel.period_end,
                CompositeMemberReturnFactModel.portfolio_id,
            )
            rows = session.execute(statement).scalars().all()
            completed_publication_families = _completed_publication_families(
                session,
                publication_filters=publication_identity_filters,
                selected_sequence=selected_sequence,
                period_start=period_start,
                period_end=period_end,
            )
            _validate_member_return_fact_selection(
                selecting_latest=selecting_latest,
                selected_sequence=selected_sequence,
                expected_families=(
                    completed_publication_families
                    if completed_publication_families is not None
                    else _member_return_fact_families(session, filters=filters)
                ),
                has_completed_publication=completed_publication_families is not None,
                selected_rows=rows,
            )
            return [_member_return_fact_from_row(row) for row in rows]

    def count_records(self) -> CompositeMetadataCounts:
        with self._session() as session:
            return CompositeMetadataCounts(
                definitions=session.query(CompositeDefinitionModel).count(),
                memberships=session.query(CompositeMembershipModel).count(),
                member_return_facts=session.query(CompositeMemberReturnFactModel).count(),
            )


def _missing_member_return_fact_schema_upgrade_columns(existing_columns: set[str]) -> dict[str, str]:
    return {
        column_name: column_definition
        for column_name, column_definition in MEMBER_RETURN_FACT_SCHEMA_UPGRADE_COLUMNS.items()
        if column_name not in existing_columns
    }


_store_cache: dict[str, CompositeMetadataStore] = {}


def get_composite_metadata_store(*, database_url: str | None = None) -> CompositeMetadataStore:
    return resolve_runtime_store(cache=_store_cache, factory=CompositeMetadataStore, database_url=database_url)


composite_metadata_store = RuntimeStoreProxy(get_composite_metadata_store)


def _load_json_object(raw_payload: str, *, row_identifier: str, payload_name: str) -> dict[str, Any] | None:
    return load_json_object_or_none(
        raw_payload,
        logger=logger,
        payload_name=payload_name,
        identity_name="row",
        identity_value=row_identifier,
        empty_is_absent=False,
    )


def _load_reason_codes(raw_payload: str, *, row_identifier: str) -> list[str]:
    return load_json_string_list_or_default(
        raw_payload,
        logger=logger,
        payload_name="Composite member return reason codes",
        identity_name="row",
        identity_value=row_identifier,
        default_value=[INVALID_COMPOSITE_REASON_CODES_PAYLOAD],
    )
