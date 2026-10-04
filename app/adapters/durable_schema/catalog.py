"""Verify mapped table structure without issuing DDL or reading business rows.

This module covers columns, relational identity and mapped check predicates.
Managed triggers and functions are separate contracts; table presence is not readiness.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.engine import Connection, Engine

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.adapters.durable_schema.guards import require_managed_guards
from app.adapters.durable_schema.predicates import predicate_identity


def verify_durable_schema(engine: Engine, *metadata: MetaData, managed_guards: tuple[str, ...] = ()) -> None:
    """Open a catalogue-only transaction; never bootstrap or repair a store."""
    with engine.connect() as connection:
        for tables in metadata:
            require_metadata_schema(connection, tables)
        if managed_guards:
            require_managed_guards(connection, managed_guards)


def require_metadata_schema(connection: Connection, metadata: MetaData) -> None:
    inspector = inspect(connection)
    available = set(inspector.get_table_names())
    issues: list[str] = []
    for table in metadata.sorted_tables:
        if table.name not in available:
            issues.append(f"table:{table.name}")
            continue
        issues.extend(_column_issues(inspector, table))
        issues.extend(_identity_issues(inspector, table))
        issues.extend(_index_issues(inspector, table))
        issues.extend(_foreign_key_issues(inspector, table))
        issues.extend(_check_issues(inspector, table))
    if connection.dialect.name == "postgresql":
        issues.extend(_postgres_catalog_issues(connection, metadata))
    if issues:
        raise DurableSchemaMigrationRequiredError(issues)


def _column_issues(inspector: Any, table: Table) -> list[str]:
    installed = {column["name"]: column for column in inspector.get_columns(table.name)}
    issues = []
    for expected in table.columns:
        actual = installed.get(expected.name)
        if actual is None or not _column_matches(actual, expected, inspector.bind.dialect.name):
            issues.append(f"column:{table.name}.{expected.name}")
        elif expected.server_default is not None and not _default_matches(actual.get("default"), expected):
            issues.append(f"default:{table.name}.{expected.name}")
    issues.extend(_unexpected_required_columns(table, installed))
    return issues


def _unexpected_required_columns(table: Table, installed: dict[str, Any]) -> list[str]:
    """Refuse unknown columns that make source-owned inserts impossible."""
    return [
        f"unexpected_required_column:{table.name}.{name}"
        for name, column in installed.items()
        if name not in table.columns
        and not column["nullable"]
        and column.get("default") is None
        and not column.get("computed")
        and not column.get("identity")
    ]


def _default_matches(actual: str | None, expected: Any) -> bool:
    if actual is None:
        return False
    declared = str(expected.server_default.arg)
    # Only the mapped integer constant default is normalized across quoted
    # SQLAlchemy defaults and PostgreSQL's typed catalogue rendering.
    if isinstance(expected.type, Integer):
        import re

        pattern = r"\(?\s*'?([0-9]+)'?\s*\)?(?:::(?:integer|bigint))?"
        expected_match = re.fullmatch(pattern, declared.strip())
        actual_match = re.fullmatch(pattern, actual.strip())
        return bool(expected_match and actual_match and int(expected_match[1]) == int(actual_match[1]))
    return actual.strip() == declared.strip()


def _check_issues(inspector: Any, table: Table) -> list[str]:
    installed = {item["name"]: item.get("sqltext") or "" for item in inspector.get_check_constraints(table.name)}
    context = _predicate_context(table)
    issues = []
    for constraint in _mapped_checks(table, inspector.bind.dialect.name):
        actual = installed.get(constraint.name)
        if actual is None or not _predicate_matches(actual, str(constraint.sqltext), context):
            issues.append(f"check:{table.name}.{constraint.name}")
    return issues


def _predicate_context(table: Table) -> dict[str, set[str]]:
    return {
        "text_columns": {column.name for column in table.columns if isinstance(column.type, String)},
        "integer_columns": {column.name for column in table.columns if isinstance(column.type, Integer)},
        "date_columns": {column.name for column in table.columns if isinstance(column.type, Date)},
    }


def _mapped_checks(table: Table, dialect: str) -> list[CheckConstraint]:
    return [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and _applies_to_dialect(constraint, dialect)
    ]


def _applies_to_dialect(constraint: Any, dialect: str) -> bool:
    conditional = constraint._ddl_if
    if conditional is None or conditional.dialect is None:
        return True
    selected = conditional.dialect
    return dialect == selected if isinstance(selected, str) else dialect in selected


def _predicate_matches(actual: str, expected: str, context: dict[str, set[str]]) -> bool:
    try:
        return predicate_identity(actual, **context) == predicate_identity(expected, **context)
    except ValueError:
        return False


def _postgres_catalog_issues(connection: Connection, metadata: MetaData) -> list[str]:
    return _postgres_unvalidated_issues(connection, metadata) + _postgres_invalid_index_issues(connection, metadata)


def _postgres_invalid_index_issues(connection: Connection, metadata: MetaData) -> list[str]:
    required = {(table.name, index.name) for table in metadata.tables.values() for index in table.indexes}
    rows = connection.execute(
        text(
            "SELECT t.relname, i.relname FROM pg_index k "
            "JOIN pg_class t ON t.oid = k.indrelid JOIN pg_class i ON i.oid = k.indexrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = current_schema() AND (NOT k.indisvalid OR NOT k.indisready OR NOT k.indislive)"
        )
    )
    return [f"invalid_index:{table}.{name}" for table, name in rows if (table, name) in required]


def _postgres_unvalidated_issues(connection: Connection, metadata: MetaData) -> list[str]:
    rows = connection.execute(
        text(
            "SELECT c.relname, k.conname FROM pg_constraint k "
            "JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND NOT k.convalidated"
        )
    )
    return [f"unvalidated_constraint:{table}.{name}" for table, name in rows if table in metadata.tables]


def _column_matches(actual: dict[str, Any], expected: Any, dialect: str) -> bool:
    if bool(actual["nullable"]) != expected.nullable:
        return False
    if not expected.type._compare_type_affinity(actual["type"]):
        return False
    if getattr(expected.type, "length", None) != getattr(actual["type"], "length", None):
        return False
    if dialect == "postgresql" and getattr(expected.type, "timezone", None) != getattr(
        actual["type"], "timezone", None
    ):
        return False
    return True


def _identity_issues(inspector: Any, table: Table) -> list[str]:
    expected_primary = tuple(column.name for column in table.primary_key.columns)
    actual_primary = tuple(inspector.get_pk_constraint(table.name).get("constrained_columns") or ())
    issues = [] if actual_primary == expected_primary else [f"primary_key:{table.name}"]
    expected_unique = _mapped_unique_identity(table)
    actual_unique = {
        (constraint.get("name"), tuple(constraint.get("column_names") or ()))
        for constraint in inspector.get_unique_constraints(table.name)
    }
    if actual_unique != expected_unique:
        issues.append(f"unique_constraint:{table.name}")
    return issues


def _mapped_unique_identity(table: Table) -> set[tuple[Any, ...]]:
    return {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _index_issues(inspector: Any, table: Table) -> list[str]:
    installed = {index["name"]: index for index in inspector.get_indexes(table.name)}
    issues = []
    for expected in table.indexes:
        actual = installed.get(expected.name)
        if actual is None or not _index_matches(actual, expected, inspector.bind.dialect.name):
            issues.append(f"index:{table.name}.{expected.name}")
    issues.extend(_unexpected_unique_indexes(table, installed))
    return issues


def _unexpected_unique_indexes(table: Table, installed: dict[str, Any]) -> list[str]:
    expected_names = {index.name for index in table.indexes}
    issues = []
    for name, index in installed.items():
        if index.get("unique") and name not in expected_names and not index.get("duplicates_constraint"):
            issues.append(f"unexpected_unique_index:{table.name}.{name}")
    return issues


def _index_matches(actual: dict[str, Any], expected: Any, dialect: str) -> bool:
    if tuple(actual.get("column_names") or ()) != tuple(column.name for column in expected.columns):
        return False
    if bool(actual.get("unique")) != bool(expected.unique):
        return False
    # A same-named partial index does not enforce the mapped all-row identity.
    actual_where = actual.get("dialect_options", {}).get(f"{dialect}_where")
    expected_where = expected.dialect_options[dialect].get("where")
    return (str(actual_where) if actual_where is not None else None) == (
        str(expected_where) if expected_where is not None else None
    )


def _foreign_key_issues(inspector: Any, table: Table) -> list[str]:
    constraints = [constraint for constraint in table.constraints if isinstance(constraint, ForeignKeyConstraint)]
    declared_names = {
        (tuple(element.parent.name for element in constraint.elements), constraint.referred_table.name): constraint.name
        for constraint in constraints
    }
    actual = {
        _foreign_key_identity(item, inspector.default_schema_name, declared_names)
        for item in inspector.get_foreign_keys(table.name)
    }
    expected = {_mapped_foreign_key_identity(constraint, inspector.default_schema_name) for constraint in constraints}
    return [] if actual == expected else [f"foreign_key:{table.name}"]


def _mapped_foreign_key_identity(constraint: ForeignKeyConstraint, default_schema: str) -> tuple[Any, ...]:
    options = {
        "ondelete": constraint.ondelete,
        "onupdate": constraint.onupdate,
        "deferrable": constraint.deferrable,
        "initially": constraint.initially,
    }
    return (
        constraint.name,
        tuple(element.parent.name for element in constraint.elements),
        constraint.referred_table.name,
        constraint.referred_table.schema or default_schema,
        tuple(element.column.name for element in constraint.elements),
        *_foreign_key_actions(options),
    )


def _foreign_key_identity(
    item: dict[str, Any], default_schema: str, declared_names: dict[tuple[Any, ...], str | None]
) -> tuple[Any, ...]:
    options = item.get("options") or {}
    columns = tuple(item.get("constrained_columns") or ())
    shape = (columns, item.get("referred_table"))
    # PostgreSQL supplies names for source-declared anonymous constraints. A
    # source-owned explicit name remains mandatory; structural identity always applies.
    name = None if shape in declared_names and declared_names[shape] is None else item.get("name")
    return (
        name,
        columns,
        item.get("referred_table"),
        item.get("referred_schema") or default_schema,
        tuple(item.get("referred_columns") or ()),
        *_foreign_key_actions(options),
    )


def _foreign_key_actions(options: dict[str, Any]) -> tuple[Any, ...]:
    return (
        options.get("ondelete") or "NO ACTION",
        options.get("onupdate") or "NO ACTION",
        bool(options.get("deferrable")),
        options.get("initially") or "IMMEDIATE",
    )
