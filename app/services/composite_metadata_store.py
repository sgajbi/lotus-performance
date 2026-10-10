from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date as dt_date
from hashlib import sha256
from typing import Any, Iterator

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    and_,
    cast,
    event,
    func,
    inspect,
    literal,
    or_,
    select,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.adapters.composite_external_fact_schema import upgrade_external_fact_columns
from app.adapters.composite_materialization_records import CompositeMaterializationModel, create_materialization_schema
from app.adapters.composite_materialization_schema import require_materialization_schema
from app.adapters.composite_materialization_view_upgrade import upgrade_materialization_return_views
from app.adapters.composite_model_fee_profile_records import ModelFeeProfileBase
from app.adapters.composite_model_fee_profile_schema import (
    create_model_fee_profile_schema,
    model_fee_profile_guard_statements,
)
from app.adapters.composite_schema_policy import (
    CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
    POSTGRES_STRIP_CHARACTERS_SQL,
    POSTGRES_TENANT_ID_CHECK_SQL,
    SQLITE_POSITIVE_INTEGER_SEQUENCE_CHECK_SQL,
    SQLITE_PUBLICATION_DATE_CHECK_SQL,
    SQLITE_STRIP_CHARACTERS_SQL,
    SQLITE_TENANT_ID_CHECK_SQL,
)
from app.adapters.durable_schema.predicates import predicate_identity
from app.adapters.durable_schema.statements import SchemaStatements, SchemaStatementWriter
from app.models.composites import (
    CompositeDefinition,
    CompositeMemberReturnFact,
    CompositeMembership,
    CompositeReturnView,
)
from app.observability import tenant_id_var
from app.services.core_tenant_authority import admitted_tenant_authority, require_composite_tenant_authority
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
MEMBER_RETURN_FACT_IMMUTABLE_TRUNCATE_TRIGGER = "trg_composite_member_return_facts_immutable_truncate"
MEMBER_RETURN_FACT_COMPLETED_INSERT_TRIGGER = "trg_composite_member_return_facts_completed_insert"
MEMBER_RETURN_FACT_COMPLETED_DELETE_TRIGGER = "trg_composite_member_return_facts_completed_delete"
POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_SQL = (
    "length(btrim(restatement_version, " + POSTGRES_STRIP_CHARACTERS_SQL + ")) > 0"
)
POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_MARKER = "chr(12288)"
SQLITE_MEMBER_RETURN_FACT_VERSION_CHECK_SQL = (
    "length(restatement_version) BETWEEN 1 AND 64 AND length(trim(restatement_version, "
    + SQLITE_STRIP_CHARACTERS_SQL
    + ")) > 0"
)
PUBLICATION_CURRENCY_CHECK = "ck_composite_fact_publications_reporting_currency_canonical"
PUBLICATION_SEQUENCE_CHECK = "ck_composite_fact_publications_restatement_sequence_positive"
PUBLICATION_SQLITE_SEQUENCE_TYPE_CHECK = "ck_composite_fact_publications_restatement_sequence_sqlite_integer"
PUBLICATION_PERIOD_CHECK = "ck_composite_fact_publications_period_valid"
PUBLICATION_PERIOD_CHECK_SQL = (
    "period_start >= '0001-01-01' AND period_end <= '9999-12-31' AND period_end >= period_start"
)
PUBLICATION_SQLITE_DATE_CHECK = "ck_composite_fact_publications_period_sqlite_dates"
PUBLICATION_IMMUTABLE_UPDATE_TRIGGER = "trg_composite_fact_publications_immutable_update"
PUBLICATION_IMMUTABLE_DELETE_TRIGGER = "trg_composite_fact_publications_immutable_delete"
PUBLICATION_IMMUTABLE_TRUNCATE_TRIGGER = "trg_composite_fact_publications_immutable_truncate"
POSTGRES_CANONICAL_REPORTING_CURRENCY_CHECK_SQL = (
    "length(reporting_currency) = 3 "
    "AND reporting_currency = upper(reporting_currency) "
    "AND substr(reporting_currency, 1, 1) >= 'A' "
    "AND substr(reporting_currency, 1, 1) <= 'Z' "
    "AND substr(reporting_currency, 2, 1) >= 'A' "
    "AND substr(reporting_currency, 2, 1) <= 'Z' "
    "AND substr(reporting_currency, 3, 1) >= 'A' "
    "AND substr(reporting_currency, 3, 1) <= 'Z'"
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
        CheckConstraint(SQLITE_TENANT_ID_CHECK_SQL, name="ck_composite_definitions_tenant_id").ddl_if(dialect="sqlite"),
        CheckConstraint(POSTGRES_TENANT_ID_CHECK_SQL, name="ck_composite_definitions_tenant_id").ddl_if(
            dialect="postgresql"
        ),
        Index(
            "uq_composite_definitions_tenant_composite",
            "tenant_id",
            "composite_id",
            unique=True,
        ),
    )

    definition_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    composite_id: Mapped[str] = mapped_column(String(128), nullable=False)
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
        ForeignKeyConstraint(
            ["tenant_id", "composite_id"],
            ["composite_definitions.tenant_id", "composite_definitions.composite_id"],
            name="fk_composite_memberships_tenant_definition",
        ),
        CheckConstraint(SQLITE_TENANT_ID_CHECK_SQL, name="ck_composite_memberships_tenant_id").ddl_if(dialect="sqlite"),
        CheckConstraint(POSTGRES_TENANT_ID_CHECK_SQL, name="ck_composite_memberships_tenant_id").ddl_if(
            dialect="postgresql"
        ),
        Index(
            "ix_composite_memberships_composite_effective",
            "tenant_id",
            "composite_id",
            "effective_from",
            "effective_to",
        ),
        Index(
            "ix_composite_memberships_portfolio_effective",
            "tenant_id",
            "portfolio_id",
            "effective_from",
            "effective_to",
        ),
    )

    membership_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
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
            "source_authority_identity_json IS NOT NULL OR "
            "(ending_market_value IS NOT NULL AND calculation_id IS NOT NULL)",
            name="ck_composite_fact_internal_evidence",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "composite_id"],
            ["composite_definitions.tenant_id", "composite_definitions.composite_id"],
            name="fk_composite_member_return_facts_tenant_definition",
        ),
        CheckConstraint(SQLITE_TENANT_ID_CHECK_SQL, name="ck_composite_member_return_facts_tenant_id").ddl_if(
            dialect="sqlite"
        ),
        CheckConstraint(POSTGRES_TENANT_ID_CHECK_SQL, name="ck_composite_member_return_facts_tenant_id").ddl_if(
            dialect="postgresql"
        ),
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
        CheckConstraint(
            POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_SQL,
            name=MEMBER_RETURN_FACT_VERSION_CHECK,
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_composite_member_return_facts_composite_period",
            "tenant_id",
            "composite_id",
            "period_start",
            "period_end",
        ),
        Index(
            "ix_composite_member_return_facts_portfolio_period",
            "tenant_id",
            "portfolio_id",
            "period_start",
            "period_end",
        ),
        Index("ix_composite_member_return_facts_status", "status"),
        Index(
            "uq_composite_member_return_facts_sequence_identity",
            "tenant_id",
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
            "tenant_id",
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
            "tenant_id",
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
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    composite_id: Mapped[str] = mapped_column(String(128), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String(128), nullable=False)
    period_start: Mapped[dt_date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt_date] = mapped_column(Date, nullable=False)
    return_value: Mapped[str] = mapped_column(Text, nullable=False)
    return_view: Mapped[str] = mapped_column(String(32), nullable=False)
    beginning_market_value: Mapped[str] = mapped_column(Text, nullable=False)
    ending_market_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    calculation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_authority_identity_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_snapshot_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(256), nullable=False)
    restatement_version: Mapped[str] = mapped_column(String(64), nullable=False)
    restatement_sequence: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False)


class CompositeMemberReturnFactPublicationModel(Base):
    __tablename__ = "composite_member_return_fact_publications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "composite_id"],
            ["composite_definitions.tenant_id", "composite_definitions.composite_id"],
            name="fk_composite_fact_publications_tenant_definition",
        ),
        CheckConstraint(SQLITE_TENANT_ID_CHECK_SQL, name="ck_composite_fact_publications_tenant_id").ddl_if(
            dialect="sqlite"
        ),
        CheckConstraint(POSTGRES_TENANT_ID_CHECK_SQL, name="ck_composite_fact_publications_tenant_id").ddl_if(
            dialect="postgresql"
        ),
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
            PUBLICATION_PERIOD_CHECK_SQL,
            name=PUBLICATION_PERIOD_CHECK,
        ),
        CheckConstraint(
            SQLITE_PUBLICATION_DATE_CHECK_SQL,
            name=PUBLICATION_SQLITE_DATE_CHECK,
        ).ddl_if(dialect="sqlite"),
        Index(
            "uq_composite_fact_publication_identity",
            "tenant_id",
            "composite_id",
            "return_view",
            "reporting_currency",
            "restatement_sequence",
            unique=True,
        ),
    )

    publication_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
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


def _scoped_key(values: dict[str, object]) -> str:
    identity = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{sha256(identity.encode('utf-8')).hexdigest()}"


def _definition_key(*, tenant_id: str, composite_id: str) -> str:
    return _scoped_key({"tenant_id": tenant_id, "composite_id": composite_id})


def _membership_key(membership: CompositeMembership, *, tenant_id: str) -> str:
    effective_to = membership.effective_to.isoformat() if membership.effective_to else "open"
    return _scoped_key(
        {
            "tenant_id": tenant_id,
            "composite_id": membership.composite_id,
            "portfolio_id": membership.portfolio_id,
            "effective_from": membership.effective_from,
            "effective_to": effective_to,
        }
    )


class CompositeMemberReturnFactConflictError(ValueError):
    """The immutable fact identity already exists with different economics or lineage."""


class CompositeDefinitionIdentityConflictError(ValueError):
    """A definition key is bound to a different tenant/composite logical identity."""


class CompositeDefinitionOwnershipError(ValueError):
    """A tenant-scoped child write has no definition owned by that tenant."""


class CompositeMemberReturnFactSelectionError(ValueError):
    """The explicit selection is absent or the unpinned latest sequence is incomplete."""


class CompositeTenantMigrationRequiredError(RuntimeError):
    """Legacy ownerless composite rows require an explicit, reviewed tenant mapping."""


class CompositeMaterializationMaintenanceRequiredError(ValueError):
    """Fact-only maintenance cannot remove a governed materialization's evidence."""


def _require_materialization_safe_maintenance(
    connection: Connection, *, tenant_id: str, composite_ids: set[str] | None
) -> None:
    statement = select(CompositeMaterializationModel.materialization_id).where(
        CompositeMaterializationModel.tenant_id == tenant_id
    )
    if composite_ids is not None:
        statement = statement.where(CompositeMaterializationModel.composite_id.in_(composite_ids))
    if connection.execute(statement.limit(1)).first() is not None:
        raise CompositeMaterializationMaintenanceRequiredError(
            "Governed materialization evidence requires coordinated retention maintenance; "
            "fact-only cleanup is refused without removing records."
        )


@dataclass(frozen=True)
class _CompositeTenantTableShape:
    identity_columns: frozenset[str]
    primary_key: tuple[str, ...]
    tenant_unique_indexes: dict[str, tuple[str, ...]]
    tenant_check_name: str
    definition_foreign_key_name: str | None = None


COMPOSITE_TENANT_TABLE_SHAPES = {
    "composite_definitions": _CompositeTenantTableShape(
        identity_columns=frozenset({"definition_key", "tenant_id", "composite_id"}),
        primary_key=("definition_key",),
        tenant_unique_indexes={
            "uq_composite_definitions_tenant_composite": ("tenant_id", "composite_id"),
        },
        tenant_check_name="ck_composite_definitions_tenant_id",
    ),
    "composite_memberships": _CompositeTenantTableShape(
        identity_columns=frozenset(
            {"membership_key", "tenant_id", "composite_id", "portfolio_id", "effective_from", "effective_to"}
        ),
        primary_key=("membership_key",),
        tenant_unique_indexes={},
        tenant_check_name="ck_composite_memberships_tenant_id",
        definition_foreign_key_name="fk_composite_memberships_tenant_definition",
    ),
    "composite_member_return_facts": _CompositeTenantTableShape(
        identity_columns=frozenset(
            {
                "fact_key",
                "tenant_id",
                "composite_id",
                "portfolio_id",
                "period_start",
                "period_end",
                "return_view",
                "reporting_currency",
                "restatement_version",
                "restatement_sequence",
            }
        ),
        primary_key=("fact_key",),
        tenant_unique_indexes={
            "uq_composite_member_return_facts_sequence_identity": (
                "tenant_id",
                "composite_id",
                "portfolio_id",
                "period_start",
                "period_end",
                "return_view",
                "reporting_currency",
                "restatement_sequence",
            ),
            "uq_composite_member_return_facts_version_identity": (
                "tenant_id",
                "composite_id",
                "portfolio_id",
                "period_start",
                "period_end",
                "return_view",
                "reporting_currency",
                "restatement_version",
            ),
        },
        tenant_check_name="ck_composite_member_return_facts_tenant_id",
        definition_foreign_key_name="fk_composite_member_return_facts_tenant_definition",
    ),
    "composite_member_return_fact_publications": _CompositeTenantTableShape(
        identity_columns=frozenset(
            {
                "publication_key",
                "tenant_id",
                "composite_id",
                "return_view",
                "reporting_currency",
                "restatement_sequence",
            }
        ),
        primary_key=("publication_key",),
        tenant_unique_indexes={
            "uq_composite_fact_publication_identity": (
                "tenant_id",
                "composite_id",
                "return_view",
                "reporting_currency",
                "restatement_sequence",
            ),
        },
        tenant_check_name="ck_composite_fact_publications_tenant_id",
        definition_foreign_key_name="fk_composite_fact_publications_tenant_definition",
    ),
}


def _identity_column_shape_issues(columns: dict[str, Any], target: _CompositeTenantTableShape) -> list[str]:
    issues: list[str] = []
    missing_identity_columns = sorted(target.identity_columns - columns.keys())
    if missing_identity_columns:
        issues.append("missing identity columns " + ", ".join(missing_identity_columns))
    tenant_column = columns.get("tenant_id")
    if tenant_column is not None and tenant_column["nullable"]:
        issues.append("tenant_id is nullable")
    return issues


def _primary_key_shape_issues(inspector: Any, table_name: str, expected: tuple[str, ...]) -> list[str]:
    installed_primary_key = tuple(inspector.get_pk_constraint(table_name).get("constrained_columns") or ())
    return (
        []
        if installed_primary_key == expected
        else [f"primary key is {installed_primary_key!r}, expected {expected!r}"]
    )


def _installed_unique_indexes(inspector: Any, table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(table_name)
        if index.get("unique") and index.get("name")
    }


def _required_unique_index_shape_issues(
    installed: dict[str, tuple[str, ...]],
    expected: dict[str, tuple[str, ...]],
) -> list[str]:
    return [
        f"unique index {index_name} is {installed.get(index_name)!r}, expected {expected_columns!r}"
        for index_name, expected_columns in expected.items()
        if installed.get(index_name) != expected_columns
    ]


def _global_unique_index_shape_issues(
    installed: dict[str, tuple[str, ...]],
    expected: dict[str, tuple[str, ...]],
) -> list[str]:
    return [
        f"global unique index {index_name} uses {installed_columns!r}"
        for index_name, installed_columns in installed.items()
        if index_name not in expected and "tenant_id" not in installed_columns
    ]


def _global_unique_constraint_shape_issues(inspector: Any, table_name: str) -> list[str]:
    constraints = inspector.get_unique_constraints(table_name)
    return [
        f"global unique constraint {constraint.get('name')!r} uses {tuple(constraint.get('column_names') or ())!r}"
        for constraint in constraints
        if "tenant_id" not in tuple(constraint.get("column_names") or ())
    ]


def _tenant_check_shape_issues(
    inspector: Any,
    table_name: str,
    target: _CompositeTenantTableShape,
) -> list[str]:
    installed = {
        constraint["name"]: constraint.get("sqltext") or ""
        for constraint in inspector.get_check_constraints(table_name)
    }
    expected_sql = (
        POSTGRES_TENANT_ID_CHECK_SQL if inspector.bind.dialect.name == "postgresql" else SQLITE_TENANT_ID_CHECK_SQL
    )
    installed_sql = installed.get(target.tenant_check_name)
    if _postgres_check_is_current(installed_sql, expected_sql):
        return []
    return [f"tenant check {target.tenant_check_name} is missing or stale"]


def _definition_foreign_key_shape_issues(
    inspector: Any,
    table_name: str,
    target: _CompositeTenantTableShape,
) -> list[str]:
    if target.definition_foreign_key_name is None:
        return []
    foreign_keys = {foreign_key.get("name"): foreign_key for foreign_key in inspector.get_foreign_keys(table_name)}
    installed = foreign_keys.get(target.definition_foreign_key_name)
    installed_shape = (
        {
            "constrained_columns": tuple(installed.get("constrained_columns") or ()),
            "referred_columns": tuple(installed.get("referred_columns") or ()),
            "referred_table": installed.get("referred_table"),
        }
        if installed is not None
        else None
    )
    expected_shape = {
        "constrained_columns": ("tenant_id", "composite_id"),
        "referred_columns": ("tenant_id", "composite_id"),
        "referred_table": "composite_definitions",
    }
    if installed_shape == expected_shape:
        return []
    return [f"foreign key {target.definition_foreign_key_name} is missing or stale"]


def _composite_table_shape_issues(
    inspector: Any,
    table_name: str,
    target: _CompositeTenantTableShape,
) -> list[str]:
    columns = {column["name"]: column for column in inspector.get_columns(table_name)}
    installed_unique_indexes = _installed_unique_indexes(inspector, table_name)
    return [
        *_identity_column_shape_issues(columns, target),
        *_primary_key_shape_issues(inspector, table_name, target.primary_key),
        *_required_unique_index_shape_issues(installed_unique_indexes, target.tenant_unique_indexes),
        *_global_unique_index_shape_issues(installed_unique_indexes, target.tenant_unique_indexes),
        *_global_unique_constraint_shape_issues(inspector, table_name),
        *_tenant_check_shape_issues(inspector, table_name, target),
        *_definition_foreign_key_shape_issues(inspector, table_name, target),
    ]


def _partial_composite_table_shapes(inspector: Any, existing_tables: set[str]) -> dict[str, list[str]]:
    return {
        table_name: issues
        for table_name in sorted(existing_tables)
        if (issues := _composite_table_shape_issues(inspector, table_name, COMPOSITE_TENANT_TABLE_SHAPES[table_name]))
    }


def _composite_table_has_rows(connection: Connection, table_name: str) -> bool:
    table = Base.metadata.tables[table_name]
    return connection.execute(select(literal(1)).select_from(table).limit(1)).first() is not None


def _populated_composite_tables(connection: Connection, existing_tables: set[str]) -> list[str]:
    return [table_name for table_name in sorted(existing_tables) if _composite_table_has_rows(connection, table_name)]


def _rebuild_empty_composite_tables(connection: Connection) -> None:
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(connection, checkfirst=True)
    # This helper runs inside ``create_durable_schema``'s locked transaction. Create
    # the replacement tables individually so the repository's direct-create-all
    # guard continues to enforce the shared concurrent-bootstrap boundary.
    for table in Base.metadata.sorted_tables:
        table.create(connection)


def _upgrade_empty_legacy_composite_schema_for_tenant_scope(connection: Connection) -> None:
    """Rebuild only an empty partial tenant schema; never infer ownership for durable rows."""

    inspector = inspect(connection)
    existing_tables = set(COMPOSITE_TENANT_TABLE_SHAPES).intersection(inspector.get_table_names())
    partial_shapes = _partial_composite_table_shapes(inspector, existing_tables)
    if not partial_shapes or _populated_composite_tables(connection, existing_tables):
        return
    _rebuild_empty_composite_tables(connection)


def _current_partial_composite_table_shapes(connection: Connection) -> tuple[set[str], dict[str, list[str]]]:
    inspector = inspect(connection)
    existing_tables = set(COMPOSITE_TENANT_TABLE_SHAPES).intersection(inspector.get_table_names())
    return existing_tables, _partial_composite_table_shapes(inspector, existing_tables)


def _raise_partial_composite_tenant_schema(
    connection: Connection,
    existing_tables: set[str],
    partial_shapes: dict[str, list[str]],
) -> None:
    populated_tables = _populated_composite_tables(connection, existing_tables)
    shape_evidence = "; ".join(f"{table_name}: {', '.join(issues)}" for table_name, issues in partial_shapes.items())
    raise CompositeTenantMigrationRequiredError(
        "Partial composite schema records cannot be assigned automatically. Supply an explicit, "
        "reviewed tenant migration before upgrading. Populated tables: "
        + (", ".join(populated_tables) or "none")
        + ". Incompatible shapes: "
        + shape_evidence
    )


def _require_current_composite_tenant_schema(connection: Connection) -> None:
    """Refuse populated partial target shapes before any schema mutation."""

    existing_tables, partial_shapes = _current_partial_composite_table_shapes(connection)
    if not partial_shapes:
        return
    _raise_partial_composite_tenant_schema(connection, existing_tables, partial_shapes)


def _require_current_composite_tenant_schema_after_upgrades(connection: Connection) -> None:
    existing_tables, partial_shapes = _current_partial_composite_table_shapes(connection)
    if partial_shapes:
        _raise_partial_composite_tenant_schema(connection, existing_tables, partial_shapes)


def _create_composite_definition_indexes(connection: Connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("composite_definitions")}
    if {"definition_key", "tenant_id", "composite_id"} <= columns:
        for index in CompositeDefinitionModel.__table__.indexes:
            index.create(connection, checkfirst=True)


def _upgrade_postgres_tenant_constraints(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    managed_constraints = {
        "composite_definitions": "ck_composite_definitions_tenant_id",
        "composite_memberships": "ck_composite_memberships_tenant_id",
        "composite_member_return_facts": "ck_composite_member_return_facts_tenant_id",
        "composite_member_return_fact_publications": "ck_composite_fact_publications_tenant_id",
    }
    for table_name, constraint_name in managed_constraints.items():
        columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
        if "tenant_id" not in columns:
            continue
        installed = {
            constraint["name"]: constraint.get("sqltext") or ""
            for constraint in inspect(connection).get_check_constraints(table_name)
        }
        _replace_stale_postgres_check_constraints(
            connection,
            table_name,
            installed,
            {constraint_name: (POSTGRES_TENANT_ID_CHECK_SQL, POSTGRES_TENANT_ID_CHECK_SQL)},
        )


def _fact_identity_values(fact: CompositeMemberReturnFact, *, tenant_id: str | None = None) -> dict[str, str | int]:
    tenant_id = _admitted_composite_tenant_id(tenant_id)
    return {
        "tenant_id": tenant_id,
        "composite_id": fact.composite_id,
        "portfolio_id": fact.portfolio_id,
        "period_start": fact.period_start.isoformat(),
        "period_end": fact.period_end.isoformat(),
        "return_view": fact.return_view.value,
        "reporting_currency": fact.reporting_currency,
        "restatement_version": fact.restatement_version,
        "restatement_sequence": fact.restatement_sequence,
    }


def _fact_key(fact: CompositeMemberReturnFact, *, tenant_id: str | None = None) -> str:
    identity = json.dumps(_fact_identity_values(fact, tenant_id=tenant_id), sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(identity.encode('utf-8')).hexdigest()}"


def _publication_key(
    *,
    tenant_id: str | None = None,
    composite_id: str,
    return_view: CompositeReturnView,
    reporting_currency: str,
    restatement_sequence: int,
) -> str:
    tenant_id = _admitted_composite_tenant_id(tenant_id)
    identity = json.dumps(
        {
            "tenant_id": tenant_id,
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


def _advisory_lock_key(scope: str, *, tenant_id: str, composite_id: str | None = None) -> int:
    values: dict[str, object] = {"scope": scope, "tenant_id": tenant_id}
    if composite_id is not None:
        values["composite_id"] = composite_id
    return _publication_lock_key(_scoped_key(values))


def _lock_composite_tenant_identity(session: Session, tenant_id: str, *, exclusive: bool) -> None:
    if session.bind is None:
        return
    if session.bind.dialect.name == "sqlite":
        if not session.in_transaction():
            session.execute(text("BEGIN IMMEDIATE"))
        return
    if session.bind.dialect.name == "postgresql":
        lock_function = func.pg_advisory_xact_lock if exclusive else func.pg_advisory_xact_lock_shared
        session.execute(select(lock_function(_advisory_lock_key("composite-tenant-maintenance", tenant_id=tenant_id))))


def _lock_composite_definition_identity(
    session: Session,
    *,
    tenant_id: str,
    composite_id: str,
    exclusive: bool,
) -> None:
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    lock_function = func.pg_advisory_xact_lock if exclusive else func.pg_advisory_xact_lock_shared
    session.execute(
        select(
            lock_function(
                _advisory_lock_key(
                    "composite-definition",
                    tenant_id=tenant_id,
                    composite_id=composite_id,
                )
            )
        )
    )


def _lock_composite_maintenance_scope(
    connection: Connection,
    *,
    tenant_id: str,
    composite_ids: set[str] | None,
) -> None:
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        return
    if connection.dialect.name != "postgresql":
        return
    tenant_lock_function = func.pg_advisory_xact_lock if composite_ids is None else func.pg_advisory_xact_lock_shared
    connection.execute(
        select(tenant_lock_function(_advisory_lock_key("composite-tenant-maintenance", tenant_id=tenant_id)))
    )
    for composite_id in sorted(composite_ids or ()):
        connection.execute(
            select(
                func.pg_advisory_xact_lock(
                    _advisory_lock_key(
                        "composite-definition",
                        tenant_id=tenant_id,
                        composite_id=composite_id,
                    )
                )
            )
        )


def _require_composite_definition_for_write(
    session: Session,
    *,
    tenant_id: str,
    composite_id: str,
) -> None:
    definition_key = _definition_key(tenant_id=tenant_id, composite_id=composite_id)
    exists = session.scalar(
        select(CompositeDefinitionModel.definition_key).where(
            CompositeDefinitionModel.definition_key == definition_key,
            CompositeDefinitionModel.tenant_id == tenant_id,
            CompositeDefinitionModel.composite_id == composite_id,
        )
    )
    if exists is None:
        raise CompositeDefinitionOwnershipError("Composite definition is unavailable for this tenant-scoped write")


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
        if not session.in_transaction():
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


def _parse_canonical_family_date(raw_value: Any) -> dt_date:
    if not isinstance(raw_value, str):
        raise ValueError("publication family periods must be ISO date strings")
    parsed_value = dt_date.fromisoformat(raw_value)
    if raw_value != parsed_value.isoformat():
        raise ValueError("publication family periods must use canonical ISO dates")
    return parsed_value


def _parse_fact_family(item: Any) -> tuple[str, dt_date, dt_date]:
    if not isinstance(item, dict) or set(item) != {"portfolio_id", "period_start", "period_end"}:
        raise ValueError("publication families contain a malformed entry")
    portfolio_id = item["portfolio_id"]
    if not isinstance(portfolio_id, str) or not portfolio_id.strip() or len(portfolio_id) > 128:
        raise ValueError("publication family portfolio_id must be nonblank")
    period_start = _parse_canonical_family_date(item["period_start"])
    period_end = _parse_canonical_family_date(item["period_end"])
    if period_end < period_start:
        raise ValueError("publication family periods must be ordered")
    return portfolio_id, period_start, period_end


def _parse_fact_families(raw_payload: Any) -> set[tuple[str, dt_date, dt_date]]:
    if not isinstance(raw_payload, str):
        raise ValueError("publication families must be encoded as JSON text")
    payload = json.loads(raw_payload)
    if not isinstance(payload, list):
        raise ValueError("publication families must be a list")
    families = {_parse_fact_family(item) for item in payload}
    if len(families) != len(payload):
        raise ValueError("publication families must not contain duplicates")
    return families


def _deserialize_fact_families(raw_payload: str) -> set[tuple[str, dt_date, dt_date]]:
    try:
        return _parse_fact_families(raw_payload)
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
            "ending_market_value": _row_value(row, "ending_market_value"),
            "reporting_currency": _row_value(row, "reporting_currency"),
            "calculation_id": _row_value(row, "calculation_id"),
            "source_authority_identity": json.loads(_row_value(row, "source_authority_identity_json"))
            if _row_value(row, "source_authority_identity_json")
            else None,
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


def _member_return_fact_model(
    fact: CompositeMemberReturnFact, *, tenant_id: str | None = None
) -> CompositeMemberReturnFactModel:
    tenant_id = _admitted_composite_tenant_id(tenant_id)
    return CompositeMemberReturnFactModel(
        fact_key=_fact_key(fact, tenant_id=tenant_id),
        tenant_id=tenant_id,
        composite_id=fact.composite_id,
        portfolio_id=fact.portfolio_id,
        period_start=fact.period_start,
        period_end=fact.period_end,
        return_value=str(fact.return_value),
        return_view=fact.return_view.value,
        beginning_market_value=str(fact.beginning_market_value),
        ending_market_value=str(fact.ending_market_value) if fact.ending_market_value is not None else None,
        reporting_currency=fact.reporting_currency,
        calculation_id=fact.calculation_id,
        source_authority_identity_json=fact.source_authority_identity.model_dump_json()
        if fact.source_authority_identity is not None
        else None,
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
    *,
    tenant_id: str,
) -> CompositeMemberReturnFactModel | None:
    statement = select(CompositeMemberReturnFactModel).where(
        CompositeMemberReturnFactModel.tenant_id == tenant_id,
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


def _publication_lineage_is_invalid(
    *,
    expected_families_json: Any,
    source_fingerprint: Any,
    period_start: dt_date,
    period_end: dt_date,
) -> bool:
    if not isinstance(source_fingerprint, str) or not source_fingerprint.strip() or len(source_fingerprint) > 256:
        return True
    try:
        expected_families = _parse_fact_families(expected_families_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return True
    return any(
        family_start < period_start or family_end > period_end for _, family_start, family_end in expected_families
    )


def _reject_invalid_publication_lineage(connection: Connection) -> None:
    table = CompositeMemberReturnFactPublicationModel.__table__
    facts_table = CompositeMemberReturnFactModel.__table__
    has_tenant_scope = "tenant_id" in {column["name"] for column in inspect(connection).get_columns(table.name)}
    retained_lineage = connection.execute(
        select(
            table.c.tenant_id if has_tenant_scope else literal(None),
            table.c.composite_id,
            table.c.return_view,
            table.c.reporting_currency,
            table.c.restatement_sequence,
            table.c.expected_families_json,
            table.c.source_fingerprint,
            table.c.period_start,
            table.c.period_end,
        )
    )
    invalid_lineage_count = 0
    for (
        tenant_id,
        composite_id,
        return_view,
        reporting_currency,
        restatement_sequence,
        expected_families_json,
        source_fingerprint,
        period_start,
        period_end,
    ) in retained_lineage:
        if _publication_lineage_is_invalid(
            expected_families_json=expected_families_json,
            source_fingerprint=source_fingerprint,
            period_start=period_start,
            period_end=period_end,
        ):
            invalid_lineage_count += 1
            continue
        expected_families = _parse_fact_families(expected_families_json)
        fact_filters = [
            facts_table.c.composite_id == composite_id,
            facts_table.c.return_view == return_view,
            facts_table.c.reporting_currency == reporting_currency,
            facts_table.c.restatement_sequence == restatement_sequence,
        ]
        if has_tenant_scope:
            fact_filters.insert(0, facts_table.c.tenant_id == tenant_id)
        actual_families = set(
            connection.execute(
                select(
                    facts_table.c.portfolio_id,
                    facts_table.c.period_start,
                    facts_table.c.period_end,
                ).where(*fact_filters)
            )
        )
        if actual_families != expected_families:
            invalid_lineage_count += 1
    if invalid_lineage_count:
        raise RuntimeError(
            "Composite member-return fact publication upgrade found "
            f"{invalid_lineage_count} row(s) with invalid publication lineage; "
            "family evidence must be a structurally valid in-window manifest that exactly matches durable facts, "
            "and source_fingerprint must be nonblank"
        )


def _replace_stale_postgres_check_constraints(
    connection: Connection,
    table_name: str,
    installed_constraints: dict[str, str],
    required_constraints: dict[str, tuple[str, str]],
) -> None:
    constraints_to_replace = _stale_postgres_constraints(installed_constraints, required_constraints)
    for constraint_name, _definition, installed_definition in constraints_to_replace:
        if installed_definition is not None:
            connection.execute(text(f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name}"))
    for constraint_name, definition, _installed_definition in constraints_to_replace:
        connection.execute(text(f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} CHECK ({definition})"))


def _harden_postgres_member_return_fact_columns(
    connection: Connection,
    columns_by_name: dict[str, Any],
) -> None:
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
    if columns_by_name["reporting_currency"]["nullable"]:
        connection.execute(
            text("ALTER TABLE composite_member_return_facts ALTER COLUMN reporting_currency SET NOT NULL")
        )


def _upgrade_postgres_member_return_fact_constraints(connection: Connection) -> None:
    columns_by_name = {
        column["name"]: column for column in inspect(connection).get_columns("composite_member_return_facts")
    }
    _harden_postgres_member_return_fact_columns(connection, columns_by_name)
    check_constraints = {
        constraint["name"]: constraint.get("sqltext") or ""
        for constraint in inspect(connection).get_check_constraints("composite_member_return_facts")
    }
    required_constraints = {
        MEMBER_RETURN_FACT_CURRENCY_CHECK: (
            CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
            POSTGRES_CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
        ),
        MEMBER_RETURN_FACT_SEQUENCE_CHECK: ("restatement_sequence >= 1", "restatement_sequence >= 1"),
        MEMBER_RETURN_FACT_VERSION_CHECK: (
            POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_SQL,
            POSTGRES_MEMBER_RETURN_FACT_VERSION_CHECK_SQL,
        ),
    }
    _replace_stale_postgres_check_constraints(
        connection,
        "composite_member_return_facts",
        check_constraints,
        required_constraints,
    )


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
        (
            "expected_families_json",
            "ALTER TABLE composite_member_return_fact_publications ALTER COLUMN expected_families_json SET NOT NULL",
        ),
        (
            "source_fingerprint",
            "ALTER TABLE composite_member_return_fact_publications ALTER COLUMN source_fingerprint SET NOT NULL",
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
    check_constraints = {
        constraint["name"]: constraint.get("sqltext") or ""
        for constraint in inspect(connection).get_check_constraints(
            CompositeMemberReturnFactPublicationModel.__tablename__
        )
    }
    constraint_definitions = {
        PUBLICATION_CURRENCY_CHECK: (
            CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
            POSTGRES_CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
        ),
        PUBLICATION_SEQUENCE_CHECK: ("restatement_sequence >= 1", "restatement_sequence >= 1"),
        PUBLICATION_PERIOD_CHECK: (PUBLICATION_PERIOD_CHECK_SQL, PUBLICATION_PERIOD_CHECK_SQL),
    }
    # Constraint names are not semantics. Early schemas used these governed names
    # for weaker definitions. Compare PostgreSQL's normalized reflected expression
    # before replacing a managed check so a canonical bootstrap remains DDL-free.
    _replace_stale_postgres_check_constraints(
        connection,
        "composite_member_return_fact_publications",
        check_constraints,
        constraint_definitions,
    )


def _postgres_check_is_current(
    installed_definition: str | None,
    postgres_definition: str,
) -> bool:
    if installed_definition is None:
        return False
    context = {
        "text_columns": {"tenant_id", "reporting_currency", "restatement_version"},
        "integer_columns": {"restatement_sequence"},
        "date_columns": {"period_start", "period_end"},
    }
    try:
        return predicate_identity(installed_definition, **context) == predicate_identity(postgres_definition, **context)
    except ValueError:
        return False


def _stale_postgres_constraints(
    installed_constraints: dict[str, str],
    required_constraints: dict[str, tuple[str, str]],
) -> list[tuple[str, str, str | None]]:
    return [
        (constraint_name, definition, installed_constraints.get(constraint_name))
        for constraint_name, (definition, postgres_definition) in required_constraints.items()
        if not _postgres_check_is_current(
            installed_constraints.get(constraint_name),
            postgres_definition,
        )
    ]


def _upgrade_publication_schema(connection: Connection) -> None:
    table_name = CompositeMemberReturnFactPublicationModel.__tablename__
    _require_publication_lineage_columns(connection)
    _add_missing_publication_columns(connection)
    _reject_invalid_publication_sequences(connection)
    _reject_invalid_publication_periods(connection)
    _reject_invalid_publication_lineage(connection)
    if connection.dialect.name == "postgresql":
        _upgrade_postgres_publication_constraints(connection)
    if "tenant_id" in {column["name"] for column in inspect(connection).get_columns(table_name)}:
        for index in CompositeMemberReturnFactPublicationModel.__table__.indexes:
            index.create(connection, checkfirst=True)


def _upgrade_postgres_definition_currency_constraint(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    table_name = CompositeDefinitionModel.__tablename__
    columns_by_name = {column["name"]: column for column in inspect(connection).get_columns(table_name)}
    if columns_by_name["reporting_currency"]["nullable"]:
        connection.execute(text("ALTER TABLE composite_definitions ALTER COLUMN reporting_currency SET NOT NULL"))
    check_constraints = {
        constraint["name"]: constraint.get("sqltext") or ""
        for constraint in inspect(connection).get_check_constraints(table_name)
    }
    _replace_stale_postgres_check_constraints(
        connection,
        table_name,
        check_constraints,
        {
            COMPOSITE_DEFINITION_CURRENCY_CHECK: (
                CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
                POSTGRES_CANONICAL_REPORTING_CURRENCY_CHECK_SQL,
            )
        },
    )


def _drop_composite_fact_database_guards(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        for trigger_name in (
            "trg_composite_definitions_validate_insert",
            "trg_composite_definitions_validate_update",
            "trg_composite_member_return_facts_validate_insert",
            MEMBER_RETURN_FACT_COMPLETED_INSERT_TRIGGER,
            "trg_composite_fact_publications_validate_insert",
            MEMBER_RETURN_FACT_IMMUTABLE_UPDATE_TRIGGER,
            MEMBER_RETURN_FACT_COMPLETED_DELETE_TRIGGER,
            PUBLICATION_IMMUTABLE_UPDATE_TRIGGER,
            PUBLICATION_IMMUTABLE_DELETE_TRIGGER,
        ):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger_name}")
        return
    if connection.dialect.name == "postgresql":
        for trigger_name, table_name in (
            (MEMBER_RETURN_FACT_IMMUTABLE_UPDATE_TRIGGER, "composite_member_return_facts"),
            (MEMBER_RETURN_FACT_COMPLETED_INSERT_TRIGGER, "composite_member_return_facts"),
            (MEMBER_RETURN_FACT_COMPLETED_DELETE_TRIGGER, "composite_member_return_facts"),
            (MEMBER_RETURN_FACT_IMMUTABLE_TRUNCATE_TRIGGER, "composite_member_return_facts"),
            (PUBLICATION_IMMUTABLE_UPDATE_TRIGGER, "composite_member_return_fact_publications"),
            (PUBLICATION_IMMUTABLE_DELETE_TRIGGER, "composite_member_return_fact_publications"),
            (PUBLICATION_IMMUTABLE_TRUNCATE_TRIGGER, "composite_member_return_fact_publications"),
            ("trg_composite_fact_publications_validate_insert", "composite_member_return_fact_publications"),
        ):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")


def _create_sqlite_composite_fact_validation_guards(connection: SchemaStatementWriter) -> None:
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
          OR typeof(NEW.source_fingerprint) != 'text'
          OR length(NEW.source_fingerprint) > 256
          OR length(trim(NEW.source_fingerprint,
              char(9) || char(10) || char(11) || char(12) || char(13) ||
              char(28) || char(29) || char(30) || char(31) || char(32) ||
              char(133) || char(160) || char(5760) || char(8192) || char(8193) ||
              char(8194) || char(8195) || char(8196) || char(8197) || char(8198) ||
              char(8199) || char(8200) || char(8201) || char(8202) || char(8232) ||
              char(8233) || char(8239) || char(8287) || char(12288))) = 0
          OR NEW.expected_families_json IS NULL
          OR typeof(NEW.expected_families_json) != 'text'
          OR NOT json_valid(NEW.expected_families_json)
          OR CASE
              WHEN json_valid(NEW.expected_families_json)
              THEN json_type(NEW.expected_families_json) != 'array'
              ELSE 0
             END
          OR CASE
              WHEN json_valid(NEW.expected_families_json)
               AND json_type(NEW.expected_families_json) = 'array'
              THEN EXISTS (
                  SELECT 1
                  FROM json_each(NEW.expected_families_json) AS family
                  WHERE CASE
                      WHEN family.type != 'object' THEN 1
                      ELSE (SELECT count(*) FROM json_each(family.value)) != 3
                        OR json_type(family.value, '$.portfolio_id') IS NOT 'text'
                        OR length(json_extract(family.value, '$.portfolio_id')) NOT BETWEEN 1 AND 128
                        OR length(trim(
                            json_extract(family.value, '$.portfolio_id'),
                            char(9) || char(10) || char(11) || char(12) || char(13) ||
                            char(28) || char(29) || char(30) || char(31) || char(32) ||
                            char(133) || char(160) || char(5760) || char(8192) || char(8193) ||
                            char(8194) || char(8195) || char(8196) || char(8197) || char(8198) ||
                            char(8199) || char(8200) || char(8201) || char(8202) || char(8232) ||
                            char(8233) || char(8239) || char(8287) || char(12288)
                        )) = 0
                        OR json_type(family.value, '$.period_start') IS NOT 'text'
                        OR json_type(family.value, '$.period_end') IS NOT 'text'
                        OR json_extract(family.value, '$.period_start')
                           NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                        OR json_extract(family.value, '$.period_end')
                           NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                        OR julianday(json_extract(family.value, '$.period_start')) IS NULL
                        OR julianday(json_extract(family.value, '$.period_end')) IS NULL
                        OR date(julianday(json_extract(family.value, '$.period_start')))
                           != json_extract(family.value, '$.period_start')
                        OR date(julianday(json_extract(family.value, '$.period_end')))
                           != json_extract(family.value, '$.period_end')
                        OR json_extract(family.value, '$.period_end')
                           < json_extract(family.value, '$.period_start')
                        OR json_extract(family.value, '$.period_start') < NEW.period_start
                        OR json_extract(family.value, '$.period_end') > NEW.period_end
                  END
              )
              ELSE 0
             END
          OR CASE
              WHEN json_valid(NEW.expected_families_json)
               AND json_type(NEW.expected_families_json) = 'array'
              THEN (
                  SELECT count(*) FROM json_each(NEW.expected_families_json)
              ) != (
                  SELECT count(DISTINCT json_array(
                      json_extract(family.value, '$.portfolio_id'),
                      json_extract(family.value, '$.period_start'),
                      json_extract(family.value, '$.period_end')
                  ))
                  FROM json_each(NEW.expected_families_json) AS family
              )
              ELSE 0
             END
          OR CASE
              WHEN json_valid(NEW.expected_families_json)
               AND json_type(NEW.expected_families_json) = 'array'
              THEN (
                  SELECT count(*)
                  FROM composite_member_return_facts AS fact
                  WHERE fact.tenant_id = NEW.tenant_id
                    AND fact.composite_id = NEW.composite_id
                    AND fact.return_view = NEW.return_view
                    AND fact.reporting_currency = NEW.reporting_currency
                    AND fact.restatement_sequence = NEW.restatement_sequence
              ) != json_array_length(NEW.expected_families_json)
              ELSE 0
             END
          OR CASE
              WHEN json_valid(NEW.expected_families_json)
               AND json_type(NEW.expected_families_json) = 'array'
              THEN EXISTS (
                  SELECT 1
                  FROM json_each(NEW.expected_families_json) AS family
                  WHERE NOT EXISTS (
                      SELECT 1
                      FROM composite_member_return_facts AS fact
                      WHERE fact.tenant_id = NEW.tenant_id
                        AND fact.composite_id = NEW.composite_id
                        AND fact.return_view = NEW.return_view
                        AND fact.reporting_currency = NEW.reporting_currency
                        AND fact.restatement_sequence = NEW.restatement_sequence
                        AND fact.portfolio_id = json_extract(family.value, '$.portfolio_id')
                        AND fact.period_start = json_extract(family.value, '$.period_start')
                        AND fact.period_end = json_extract(family.value, '$.period_end')
                  )
              )
              ELSE 0
             END
        BEGIN
            SELECT RAISE(ABORT, 'composite fact publication requires valid identity, period, lineage, and exact durable family evidence');
        END
        """
    )


def _create_sqlite_definition_currency_guards(connection: SchemaStatementWriter) -> None:
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


def _create_sqlite_member_return_fact_immutability_guards(connection: SchemaStatementWriter) -> None:
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_member_return_facts_completed_insert")
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_member_return_facts_immutable_update")
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_composite_member_return_facts_completed_delete")
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_member_return_facts_completed_insert
        BEFORE INSERT ON composite_member_return_facts
        WHEN EXISTS (
            SELECT 1
            FROM composite_member_return_fact_publications AS publication
            WHERE publication.tenant_id = NEW.tenant_id
              AND publication.composite_id = NEW.composite_id
              AND publication.return_view = NEW.return_view
              AND publication.reporting_currency = NEW.reporting_currency
              AND publication.restatement_sequence = NEW.restatement_sequence
        )
        BEGIN
            SELECT RAISE(ABORT, 'completed composite member-return facts cannot accept new families');
        END
        """
    )
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
            WHERE publication.tenant_id = OLD.tenant_id
              AND publication.composite_id = OLD.composite_id
              AND publication.return_view = OLD.return_view
              AND publication.reporting_currency = OLD.reporting_currency
              AND publication.restatement_sequence = OLD.restatement_sequence
        )
        BEGIN
            SELECT RAISE(ABORT, 'completed composite member-return facts cannot be deleted');
        END
        """
    )


def _create_sqlite_publication_immutability_guard(connection: SchemaStatementWriter) -> None:
    connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {PUBLICATION_IMMUTABLE_UPDATE_TRIGGER}")
    connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {PUBLICATION_IMMUTABLE_DELETE_TRIGGER}")
    for trigger_name, operation in (
        (PUBLICATION_IMMUTABLE_UPDATE_TRIGGER, "UPDATE"),
        (PUBLICATION_IMMUTABLE_DELETE_TRIGGER, "DELETE"),
    ):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE {operation} ON composite_member_return_fact_publications
            BEGIN
                SELECT RAISE(ABORT, 'composite fact publications are immutable; write a new restatement sequence');
            END
            """
        )


def _create_postgres_member_return_fact_immutability_guards(connection: SchemaStatementWriter) -> None:
    # The tenant argument changes the PostgreSQL function signature. PostgreSQL
    # overloads instead of replacing a function when argument types differ, so
    # remove the pre-tenant helper explicitly rather than leaving callable stale
    # lock semantics in the schema.
    connection.exec_driver_sql("DROP FUNCTION IF EXISTS composite_fact_publication_lock_key(text, text, text, bigint)")
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION composite_fact_publication_lock_key(
            p_tenant_id text,
            p_composite_id text,
            p_return_view text,
            p_reporting_currency text,
            p_restatement_sequence bigint
        )
        RETURNS bigint
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
            SELECT hashtextextended(
                p_tenant_id || chr(31) || p_composite_id || chr(31) || p_return_view || chr(31) ||
                p_reporting_currency || chr(31) || p_restatement_sequence::text,
                0
            )
        $$
        """
    )
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION fence_composite_member_return_fact_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock_shared(composite_fact_publication_lock_key(
                NEW.tenant_id,
                NEW.composite_id,
                NEW.return_view,
                NEW.reporting_currency,
                NEW.restatement_sequence
            ));
            IF EXISTS (
                SELECT 1
                FROM composite_member_return_fact_publications AS publication
                WHERE publication.tenant_id = NEW.tenant_id
                  AND publication.composite_id = NEW.composite_id
                  AND publication.return_view = NEW.return_view
                  AND publication.reporting_currency = NEW.reporting_currency
                  AND publication.restatement_sequence = NEW.restatement_sequence
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'completed composite member-return facts cannot accept new families';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION reject_composite_member_return_fact_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'TRUNCATE') THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'composite member-return facts are immutable; write a new restatement sequence';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM composite_member_return_fact_publications AS publication
                WHERE publication.tenant_id = OLD.tenant_id
                  AND publication.composite_id = OLD.composite_id
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
        f"DROP TRIGGER IF EXISTS {MEMBER_RETURN_FACT_COMPLETED_INSERT_TRIGGER} ON composite_member_return_facts"
    )
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_composite_member_return_facts_immutable_update ON composite_member_return_facts"
    )
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_composite_member_return_facts_completed_delete ON composite_member_return_facts"
    )
    connection.exec_driver_sql(
        f"""
        CREATE TRIGGER {MEMBER_RETURN_FACT_COMPLETED_INSERT_TRIGGER}
        BEFORE INSERT ON composite_member_return_facts
        FOR EACH ROW
        EXECUTE FUNCTION fence_composite_member_return_fact_insert()
        """
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
        f"DROP TRIGGER IF EXISTS {MEMBER_RETURN_FACT_IMMUTABLE_TRUNCATE_TRIGGER} ON composite_member_return_facts"
    )
    connection.exec_driver_sql(
        f"""
        CREATE TRIGGER {MEMBER_RETURN_FACT_IMMUTABLE_TRUNCATE_TRIGGER}
        BEFORE TRUNCATE ON composite_member_return_facts
        FOR EACH STATEMENT
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


def _create_postgres_publication_lineage_guard(connection: SchemaStatementWriter) -> None:
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION validate_composite_fact_publication_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            manifest jsonb;
            family jsonb;
            family_start date;
            family_end date;
            family_count integer;
            distinct_family_count integer;
            actual_family_count integer;
        BEGIN
            PERFORM pg_advisory_xact_lock(composite_fact_publication_lock_key(
                NEW.tenant_id,
                NEW.composite_id,
                NEW.return_view,
                NEW.reporting_currency,
                NEW.restatement_sequence
            ));
            IF NEW.source_fingerprint IS NULL
               OR length(NEW.source_fingerprint) > 256
               OR length(btrim(NEW.source_fingerprint,
                    chr(9) || chr(10) || chr(11) || chr(12) || chr(13) ||
                    chr(28) || chr(29) || chr(30) || chr(31) || chr(32) ||
                    chr(133) || chr(160) || chr(5760) || chr(8192) || chr(8193) ||
                    chr(8194) || chr(8195) || chr(8196) || chr(8197) || chr(8198) ||
                    chr(8199) || chr(8200) || chr(8201) || chr(8202) || chr(8232) ||
                    chr(8233) || chr(8239) || chr(8287) || chr(12288)
               )) = 0 THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'composite fact publication source fingerprint is invalid';
            END IF;
            BEGIN
                manifest := NEW.expected_families_json::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'composite fact publication family manifest is invalid JSON';
            END;
            IF manifest IS NULL OR jsonb_typeof(manifest) != 'array' THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'composite fact publication family manifest must be a JSON array';
            END IF;
            SELECT count(*), count(DISTINCT jsonb_build_array(
                value ->> 'portfolio_id', value ->> 'period_start', value ->> 'period_end'
            ))
            INTO family_count, distinct_family_count
            FROM jsonb_array_elements(manifest);
            IF family_count != distinct_family_count THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'composite fact publication family manifest contains duplicates';
            END IF;
            FOR family IN SELECT value FROM jsonb_array_elements(manifest)
            LOOP
                IF jsonb_typeof(family) != 'object' THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'composite fact publication family manifest contains a non-object entry';
                END IF;
                IF NOT (family ?& ARRAY['portfolio_id', 'period_start', 'period_end'])
                   OR (SELECT count(*) FROM jsonb_object_keys(family)) != 3
                   OR jsonb_typeof(family -> 'portfolio_id') != 'string'
                   OR length(family ->> 'portfolio_id') NOT BETWEEN 1 AND 128
                   OR length(btrim(family ->> 'portfolio_id',
                        chr(9) || chr(10) || chr(11) || chr(12) || chr(13) ||
                        chr(28) || chr(29) || chr(30) || chr(31) || chr(32) ||
                        chr(133) || chr(160) || chr(5760) || chr(8192) || chr(8193) ||
                        chr(8194) || chr(8195) || chr(8196) || chr(8197) || chr(8198) ||
                        chr(8199) || chr(8200) || chr(8201) || chr(8202) || chr(8232) ||
                        chr(8233) || chr(8239) || chr(8287) || chr(12288)
                   )) = 0
                   OR jsonb_typeof(family -> 'period_start') != 'string'
                   OR jsonb_typeof(family -> 'period_end') != 'string' THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'composite fact publication family manifest contains a malformed entry';
                END IF;
                BEGIN
                    family_start := (family ->> 'period_start')::date;
                    family_end := (family ->> 'period_end')::date;
                EXCEPTION WHEN OTHERS THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'composite fact publication family manifest contains an invalid date';
                END;
                IF family ->> 'period_start' != to_char(family_start, 'YYYY-MM-DD')
                   OR family ->> 'period_end' != to_char(family_end, 'YYYY-MM-DD')
                   OR family_end < family_start
                   OR family_start < NEW.period_start
                   OR family_end > NEW.period_end THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'composite fact publication family manifest contains an invalid period';
                END IF;
            END LOOP;
            SELECT count(*)
            INTO actual_family_count
            FROM composite_member_return_facts AS fact
            WHERE fact.tenant_id = NEW.tenant_id
              AND fact.composite_id = NEW.composite_id
              AND fact.return_view = NEW.return_view
              AND fact.reporting_currency = NEW.reporting_currency
              AND fact.restatement_sequence = NEW.restatement_sequence;
            IF actual_family_count != family_count
               OR EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(manifest) AS expected(value)
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM composite_member_return_facts AS fact
                        WHERE fact.tenant_id = NEW.tenant_id
                          AND fact.composite_id = NEW.composite_id
                          AND fact.return_view = NEW.return_view
                          AND fact.reporting_currency = NEW.reporting_currency
                          AND fact.restatement_sequence = NEW.restatement_sequence
                          AND fact.portfolio_id = expected.value ->> 'portfolio_id'
                          AND fact.period_start = (expected.value ->> 'period_start')::date
                          AND fact.period_end = (expected.value ->> 'period_end')::date
                    )
               ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'composite fact publication family manifest does not match durable facts';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS trg_composite_fact_publications_validate_insert "
        "ON composite_member_return_fact_publications"
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER trg_composite_fact_publications_validate_insert
        BEFORE INSERT ON composite_member_return_fact_publications
        FOR EACH ROW
        EXECUTE FUNCTION validate_composite_fact_publication_lineage()
        """
    )


def _create_postgres_publication_immutability_guard(connection: SchemaStatementWriter) -> None:
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION reject_composite_fact_publication_mutation()
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
        f"DROP TRIGGER IF EXISTS {PUBLICATION_IMMUTABLE_UPDATE_TRIGGER} ON composite_member_return_fact_publications"
    )
    connection.exec_driver_sql(
        f"DROP TRIGGER IF EXISTS {PUBLICATION_IMMUTABLE_DELETE_TRIGGER} ON composite_member_return_fact_publications"
    )
    connection.exec_driver_sql(
        f"DROP TRIGGER IF EXISTS {PUBLICATION_IMMUTABLE_TRUNCATE_TRIGGER} ON composite_member_return_fact_publications"
    )
    for trigger_name, operation, level in (
        (PUBLICATION_IMMUTABLE_UPDATE_TRIGGER, "UPDATE", "ROW"),
        (PUBLICATION_IMMUTABLE_DELETE_TRIGGER, "DELETE", "ROW"),
        (PUBLICATION_IMMUTABLE_TRUNCATE_TRIGGER, "TRUNCATE", "STATEMENT"),
    ):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE {operation} ON composite_member_return_fact_publications
            FOR EACH {level}
            EXECUTE FUNCTION reject_composite_fact_publication_mutation()
            """
        )


def _create_composite_fact_database_guards(connection: SchemaStatementWriter) -> None:
    if connection.dialect.name == "sqlite":
        _create_sqlite_definition_currency_guards(connection)
        _create_sqlite_composite_fact_validation_guards(connection)
        _create_sqlite_member_return_fact_immutability_guards(connection)
        _create_sqlite_publication_immutability_guard(connection)
    elif connection.dialect.name == "postgresql":
        _create_postgres_member_return_fact_immutability_guards(connection)
        _create_postgres_publication_lineage_guard(connection)
        _create_postgres_publication_immutability_guard(connection)


def composite_fact_guard_statements(dialect: Dialect) -> tuple[str, ...]:
    """Render the owner's guard contract without a database connection or DDL."""
    writer = SchemaStatements(dialect)
    _create_composite_fact_database_guards(writer)
    return tuple(writer.statements)


def _covering_publication_window_filters(period_start: dt_date, period_end: dt_date) -> tuple[Any, ...]:
    return (
        CompositeMemberReturnFactPublicationModel.period_start <= period_start,
        CompositeMemberReturnFactPublicationModel.period_end >= period_end,
    )


def _resolve_member_return_reporting_currency(
    session: Session,
    *,
    tenant_id: str,
    composite_id: str,
    period_start: dt_date,
    period_end: dt_date,
    return_view: CompositeReturnView,
    requested_currency: str | None,
    requested_sequence: int | None,
) -> str:
    if requested_currency is not None:
        return requested_currency
    publication = CompositeMemberReturnFactPublicationModel
    statement = (
        select(publication.reporting_currency)
        .where(
            publication.tenant_id == tenant_id,
            publication.composite_id == composite_id,
            publication.return_view == return_view.value,
            *_covering_publication_window_filters(period_start, period_end),
        )
        .distinct()
    )
    if requested_sequence is not None:
        statement = statement.where(publication.restatement_sequence == requested_sequence)
    currencies = session.execute(statement).scalars().all()
    if len(currencies) > 1:
        raise CompositeMemberReturnFactSelectionError(
            "Reporting currency is required when the requested scope has multiple published projections."
        )
    if currencies:
        return currencies[0]
    # Pre-publication legacy selection retains its definition default. Financial
    # facts still pass the existing completeness and release checks below.
    currency = session.execute(
        select(CompositeDefinitionModel.reporting_currency).where(
            CompositeDefinitionModel.tenant_id == tenant_id,
            CompositeDefinitionModel.composite_id == composite_id,
        )
    ).scalar_one_or_none()
    if currency is None:
        raise CompositeMemberReturnFactSelectionError("Composite reporting definition is unavailable.")
    return currency


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
    tenant_id: str,
    composite_id: str,
    return_view: CompositeReturnView,
    reporting_currency: str,
    restatement_sequence: int,
) -> CompositeMemberReturnFactPublicationModel | None:
    """Resolve a publication by its governed identity, independent of a legacy key."""

    return session.execute(
        select(CompositeMemberReturnFactPublicationModel).where(
            CompositeMemberReturnFactPublicationModel.tenant_id == tenant_id,
            CompositeMemberReturnFactPublicationModel.composite_id == composite_id,
            CompositeMemberReturnFactPublicationModel.return_view == return_view.value,
            CompositeMemberReturnFactPublicationModel.reporting_currency == reporting_currency,
            CompositeMemberReturnFactPublicationModel.restatement_sequence == restatement_sequence,
        )
    ).scalar_one_or_none()


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


class CompositeMetadataStore:
    def __init__(self, database_url: str):
        self._engine = create_durable_database_engine(database_url)
        if self._engine.dialect.name == "sqlite":
            event.listen(self._engine, "connect", _enable_sqlite_foreign_keys)
        self._session_factory = sessionmaker(bind=self._engine, future=True)

    def close(self) -> None:
        self._engine.dispose()

    def capture_result_candidate(self, *, candidate_id, request, response, principal, result_store):
        from app.adapters.composite_result_candidate_storage import capture_candidate, require_same_result_database

        require_same_result_database(self, result_store)
        with self._session() as session:
            if self._engine.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            return capture_candidate(
                session, candidate_id=candidate_id, request=request, response=response, principal=principal
            )

    def get_result_candidate(self, *, candidate_id, tenant_id, result_store, principal=None):
        from app.adapters.composite_result_candidate_storage import (
            _require_installed,
            read_candidate,
            require_same_result_database,
        )

        tenant_id = _admitted_composite_tenant_id(tenant_id)
        require_same_result_database(self, result_store)
        with self._session() as session:
            _require_installed(session.connection())
            return read_candidate(session, tenant_id=tenant_id, candidate_id=candidate_id, principal=principal)

    def create_schema(self) -> None:
        from app.adapters.composite_attribution_schema import create_attribution_schema, require_attribution_schema
        from app.adapters.composite_model_fee_profile_upgrade import upgrade_model_fee_profile_products
        from app.adapters.composite_result_authority.schema import create_authority_schema, require_authority_schema
        from app.adapters.composite_result_candidate_schema import create_candidate_schema, require_candidate_schema

        create_durable_schema(
            self._engine,
            Base.metadata,
            schema_preflights=(
                require_attribution_schema,
                require_authority_schema,
                require_candidate_schema,
                upgrade_model_fee_profile_products,
                upgrade_materialization_return_views,
                require_materialization_schema,
                _upgrade_empty_legacy_composite_schema_for_tenant_scope,
                _require_current_composite_tenant_schema,
            ),
            schema_upgrades=(
                _drop_composite_fact_database_guards,
                _upgrade_legacy_composite_currencies,
                _upgrade_postgres_definition_currency_constraint,
                self._upgrade_member_return_fact_schema,
                _upgrade_publication_schema,
                _create_composite_definition_indexes,
                _require_current_composite_tenant_schema_after_upgrades,
                _upgrade_postgres_tenant_constraints,
                _create_composite_fact_database_guards,
                create_materialization_schema,
                create_model_fee_profile_schema,
                create_candidate_schema,
                create_authority_schema,
                create_attribution_schema,
            ),
        )

    def verify_schema(self) -> None:
        from app.adapters.composite_attribution_schema import attribution_guard_statements
        from app.adapters.composite_attribution_schema import metadata as attribution_metadata
        from app.adapters.composite_result_authority.records import AuthorityBase
        from app.adapters.composite_result_authority.schema import authority_guard_statements
        from app.adapters.composite_result_candidate_records import CandidateBase
        from app.adapters.composite_result_candidate_schema import candidate_guard_statements
        from app.adapters.durable_schema.catalog import verify_durable_schema

        verify_durable_schema(
            self._engine,
            Base.metadata,
            CompositeMaterializationModel.__table__.metadata,
            ModelFeeProfileBase.metadata,
            CandidateBase.metadata,
            AuthorityBase.metadata,
            attribution_metadata,
            managed_guards=(
                *composite_fact_guard_statements(self._engine.dialect),
                *model_fee_profile_guard_statements(self._engine.dialect),
                *candidate_guard_statements(self._engine.dialect),
                *authority_guard_statements(self._engine.dialect),
                *attribution_guard_statements(self._engine.dialect),
            ),
        )

    def publish_model_fee_profile(self, profile, *, tenant_id: str, actor_id: str):
        from app.adapters.composite_model_fee_profile_storage import publish_profile

        tenant_id = _admitted_composite_tenant_id(tenant_id)
        with self._session() as session:
            if self._engine.dialect.name == "sqlite":
                # SAVEPOINT alone can commit its parent under legacy sqlite
                # transaction control. Fence the actual writer transaction
                # before retry inspection so every refusal rolls back fully.
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            return publish_profile(session, profile, tenant_id=tenant_id, actor_id=actor_id)

    def get_model_fee_profile(self, *, tenant_id: str, profile_id: str, revision: str):
        from app.adapters.composite_model_fee_profile_storage import read_profile

        tenant_id = _admitted_composite_tenant_id(tenant_id)
        with self._session() as session:
            return read_profile(session, tenant_id=tenant_id, profile_id=profile_id, revision=revision)

    def resolve_model_fee_profile(self, request):
        from app.adapters.composite_model_fee_profile_storage import resolve_profile

        _admitted_composite_tenant_id(request.tenant_id)
        with self._session() as session:
            return resolve_profile(session, request)

    def _upgrade_member_return_fact_schema(self, connection: Connection) -> None:
        existing_columns = {
            column["name"] for column in inspect(connection).get_columns("composite_member_return_facts")
        }
        _add_missing_member_return_fact_columns(connection, existing_columns)
        upgrade_external_fact_columns(connection, CompositeMemberReturnFactModel.__table__)
        _reject_invalid_member_return_fact_sequences(connection)
        _reject_invalid_member_return_fact_versions(connection)
        if connection.dialect.name == "postgresql":
            _upgrade_postgres_member_return_fact_constraints(connection)
        if "tenant_id" in existing_columns:
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

    @contextmanager
    def _unguarded_maintenance_connection(
        self,
        *,
        tenant_id: str,
        composite_ids: set[str] | None,
    ) -> Iterator[Connection]:
        """Suspend immutable guards only inside one locked rollback-safe transaction."""

        with self._engine.begin() as connection:
            _lock_composite_maintenance_scope(
                connection,
                tenant_id=tenant_id,
                composite_ids=composite_ids,
            )
            _require_materialization_safe_maintenance(connection, tenant_id=tenant_id, composite_ids=composite_ids)
            if connection.dialect.name == "postgresql":
                # Match publication completion's fact-before-publication lock
                # order so maintenance cannot form a cross-table deadlock.
                connection.exec_driver_sql("LOCK TABLE composite_member_return_facts IN ACCESS EXCLUSIVE MODE")
                connection.exec_driver_sql(
                    "LOCK TABLE composite_member_return_fact_publications IN ACCESS EXCLUSIVE MODE"
                )
            _drop_composite_fact_database_guards(connection)
            try:
                yield connection
            except Exception:
                # The surrounding transaction restores prior guards and data.
                raise
            else:
                _create_composite_fact_database_guards(connection)

    def clear_all_records(self, *, tenant_id: str | None = None) -> None:
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        with self._unguarded_maintenance_connection(tenant_id=tenant_id, composite_ids=None) as connection:
            for model in (
                CompositeMemberReturnFactPublicationModel,
                CompositeMemberReturnFactModel,
                CompositeMembershipModel,
                CompositeDefinitionModel,
            ):
                connection.execute(model.__table__.delete().where(model.tenant_id == tenant_id))

    def clear_records_for_composites(self, composite_ids: set[str], *, tenant_id: str | None = None) -> None:
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        if not composite_ids:
            return
        with self._unguarded_maintenance_connection(
            tenant_id=tenant_id,
            composite_ids=composite_ids,
        ) as connection:
            connection.execute(
                CompositeMemberReturnFactPublicationModel.__table__.delete().where(
                    CompositeMemberReturnFactPublicationModel.tenant_id == tenant_id,
                    CompositeMemberReturnFactPublicationModel.composite_id.in_(composite_ids),
                )
            )
            connection.execute(
                CompositeMemberReturnFactModel.__table__.delete().where(
                    CompositeMemberReturnFactModel.tenant_id == tenant_id,
                    CompositeMemberReturnFactModel.composite_id.in_(composite_ids),
                )
            )
            connection.execute(
                CompositeMembershipModel.__table__.delete().where(
                    CompositeMembershipModel.tenant_id == tenant_id,
                    CompositeMembershipModel.composite_id.in_(composite_ids),
                )
            )
            connection.execute(
                CompositeDefinitionModel.__table__.delete().where(
                    CompositeDefinitionModel.tenant_id == tenant_id,
                    CompositeDefinitionModel.composite_id.in_(composite_ids),
                )
            )

    def upsert_definition(self, definition: CompositeDefinition, *, tenant_id: str | None = None) -> None:
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        definition_key = _definition_key(tenant_id=tenant_id, composite_id=definition.composite_id)
        with self._session() as session:
            _lock_composite_tenant_identity(session, tenant_id, exclusive=False)
            _lock_composite_definition_identity(
                session,
                tenant_id=tenant_id,
                composite_id=definition.composite_id,
                exclusive=True,
            )
            existing = session.get(CompositeDefinitionModel, definition_key)
            if existing is not None and (
                existing.tenant_id != tenant_id or existing.composite_id != definition.composite_id
            ):
                raise CompositeDefinitionIdentityConflictError(
                    "Composite definition key is already bound to a different tenant/composite identity"
                )
            session.merge(
                CompositeDefinitionModel(
                    definition_key=definition_key,
                    tenant_id=tenant_id,
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

    def get_definition(self, composite_id: str, *, tenant_id: str | None = None) -> CompositeDefinition | None:
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        with self._session() as session:
            definition_key = _definition_key(tenant_id=tenant_id, composite_id=composite_id)
            row = session.execute(
                select(CompositeDefinitionModel).where(
                    CompositeDefinitionModel.definition_key == definition_key,
                    CompositeDefinitionModel.tenant_id == tenant_id,
                    CompositeDefinitionModel.composite_id == composite_id,
                )
            ).scalar_one_or_none()
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

    def upsert_membership(self, membership: CompositeMembership, *, tenant_id: str | None = None) -> None:
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        with self._session() as session:
            _lock_composite_tenant_identity(session, tenant_id, exclusive=False)
            _lock_composite_definition_identity(
                session,
                tenant_id=tenant_id,
                composite_id=membership.composite_id,
                exclusive=False,
            )
            _require_composite_definition_for_write(
                session,
                tenant_id=tenant_id,
                composite_id=membership.composite_id,
            )
            session.merge(
                CompositeMembershipModel(
                    membership_key=_membership_key(membership, tenant_id=tenant_id),
                    tenant_id=tenant_id,
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

    def list_memberships(self, composite_id: str, *, tenant_id: str | None = None) -> list[CompositeMembership]:
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        with self._session() as session:
            statement = (
                select(CompositeMembershipModel)
                .where(
                    CompositeMembershipModel.tenant_id == tenant_id,
                    CompositeMembershipModel.composite_id == composite_id,
                )
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

    def upsert_member_return_fact(self, fact: CompositeMemberReturnFact, *, tenant_id: str | None = None) -> None:
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        session = self._session_factory()
        try:
            publication_key = _publication_key(
                tenant_id=tenant_id,
                composite_id=fact.composite_id,
                return_view=fact.return_view,
                reporting_currency=fact.reporting_currency,
                restatement_sequence=fact.restatement_sequence,
            )
            _lock_composite_tenant_identity(session, tenant_id, exclusive=False)
            _lock_composite_definition_identity(
                session,
                tenant_id=tenant_id,
                composite_id=fact.composite_id,
                exclusive=False,
            )
            # Writers share the publication fence so independent member facts can
            # proceed concurrently. Publication completion takes the exclusive form,
            # which waits for every admitted writer before attesting the exact set.
            _lock_fact_publication_identity(session, publication_key, exclusive=False)
            _require_composite_definition_for_write(
                session,
                tenant_id=tenant_id,
                composite_id=fact.composite_id,
            )
            collision = _find_member_return_fact_identity_collision(session, fact, tenant_id=tenant_id)
            if collision is not None:
                _accept_idempotent_fact_or_raise_conflict(collision, fact)
                return
            if (
                _find_member_return_fact_publication(
                    session,
                    tenant_id=tenant_id,
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
            session.add(_member_return_fact_model(fact, tenant_id=tenant_id))
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            collision = _find_member_return_fact_identity_collision(session, fact, tenant_id=tenant_id)
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
        tenant_id: str | None = None,
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
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        _validate_member_return_fact_publication_request(
            reporting_currency=reporting_currency,
            restatement_sequence=restatement_sequence,
            period_start=period_start,
            period_end=period_end,
            expected_families=expected_families,
            source_fingerprint=source_fingerprint,
        )

        publication_key = _publication_key(
            tenant_id=tenant_id,
            composite_id=composite_id,
            return_view=return_view,
            reporting_currency=reporting_currency,
            restatement_sequence=restatement_sequence,
        )
        expected_families_json = _serialize_fact_families(expected_families)
        with self._session() as session:
            _lock_composite_tenant_identity(session, tenant_id, exclusive=False)
            _lock_composite_definition_identity(
                session,
                tenant_id=tenant_id,
                composite_id=composite_id,
                exclusive=False,
            )
            _lock_fact_publication_identity(session, publication_key, exclusive=True)
            _require_composite_definition_for_write(
                session,
                tenant_id=tenant_id,
                composite_id=composite_id,
            )
            actual_families = _member_return_fact_families(
                session,
                filters=(
                    CompositeMemberReturnFactModel.tenant_id == tenant_id,
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
                tenant_id=tenant_id,
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
                    tenant_id=tenant_id,
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
        tenant_id: str | None = None,
        composite_id: str,
        period_start: dt_date,
        period_end: dt_date,
        return_view: CompositeReturnView,
        reporting_currency: str | None,
        restatement_sequence: int | None = None,
    ) -> list[CompositeMemberReturnFact]:
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        with self._session() as session:
            reporting_currency = _resolve_member_return_reporting_currency(
                session,
                tenant_id=tenant_id,
                composite_id=composite_id,
                period_start=period_start,
                period_end=period_end,
                return_view=return_view,
                requested_currency=reporting_currency,
                requested_sequence=restatement_sequence,
            )
            publication_identity_filters = (
                CompositeMemberReturnFactPublicationModel.tenant_id == tenant_id,
                CompositeMemberReturnFactPublicationModel.composite_id == composite_id,
                CompositeMemberReturnFactPublicationModel.return_view == return_view.value,
                CompositeMemberReturnFactPublicationModel.reporting_currency == reporting_currency,
            )
            covering_publication_filters = (
                *publication_identity_filters,
                *_covering_publication_window_filters(period_start, period_end),
            )
            filters = (
                CompositeMemberReturnFactModel.tenant_id == tenant_id,
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
            unreleased = session.execute(
                select(CompositeMaterializationModel.materialization_id)
                .where(
                    CompositeMaterializationModel.tenant_id == tenant_id,
                    CompositeMaterializationModel.composite_id == composite_id,
                    CompositeMaterializationModel.return_view == return_view.value,
                    CompositeMaterializationModel.reporting_currency == reporting_currency,
                    (
                        CompositeMaterializationModel.restatement_sequence >= selected_sequence
                        if selecting_latest
                        else CompositeMaterializationModel.restatement_sequence == selected_sequence
                    ),
                    CompositeMaterializationModel.period_start <= period_end,
                    CompositeMaterializationModel.period_end >= period_start,
                    CompositeMaterializationModel.state != "COMPLETE",
                )
                .limit(1)
            ).first()
            if unreleased is not None:
                raise CompositeMemberReturnFactSelectionError("Composite materialization is not completely published.")
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

    def get_member_return_fact_materializations(self, facts, *, tenant_id: str):
        """Delegate receipt custody to its owner on this fact store's database."""
        from app.adapters.composite_materialization_repository import CompositeMaterializationStore

        with self._engine.connect() as connection:
            ledger = CompositeMaterializationStore(
                self._engine.url.render_as_string(hide_password=False), connection=connection
            )
            return ledger.get_for_member_return_facts(facts, tenant_id=tenant_id)

    def count_records(self, *, tenant_id: str | None = None) -> CompositeMetadataCounts:
        tenant_id = _admitted_composite_tenant_id(tenant_id)
        with self._session() as session:
            return CompositeMetadataCounts(
                definitions=session.query(CompositeDefinitionModel)
                .filter(CompositeDefinitionModel.tenant_id == tenant_id)
                .count(),
                memberships=session.query(CompositeMembershipModel)
                .filter(CompositeMembershipModel.tenant_id == tenant_id)
                .count(),
                member_return_facts=session.query(CompositeMemberReturnFactModel)
                .filter(CompositeMemberReturnFactModel.tenant_id == tenant_id)
                .count(),
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


def _admitted_composite_tenant_id(presented: str | None) -> str:
    authority = admitted_tenant_authority(tenant_id_var.get() if presented is None else presented)
    return require_composite_tenant_authority(authority).tenant_id


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
