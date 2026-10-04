"""Owner-only repair of legacy SQLite nullable primary-key declarations.

Only mapped tables without custom columns, indexes, triggers or foreign-key
dependencies qualify. Unknown truth and NULL identities refuse without mutation.
The caller owns a BEGIN IMMEDIATE transaction; no runtime verifier invokes this.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateTable, DropTable

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError


def upgrade_sqlite_primary_key_nullability(connection: Connection, metadata: MetaData) -> None:
    if connection.dialect.name != "sqlite":
        return
    inspector = inspect(connection)
    available = set(inspector.get_table_names())
    targets = [table for table in metadata.sorted_tables if _requires_upgrade(inspector, table, available)]
    # Validate the whole bounded migration before replacing either lineage table.
    for table in targets:
        _require_supported_table(connection, inspector, table, available)
    for table in targets:
        _replace_table(connection, table)


def _requires_upgrade(inspector: Any, table: Table, available: set[str]) -> bool:
    if table.name not in available:
        return False
    primary = set(table.primary_key.columns.keys())
    return any(column["name"] in primary and column["nullable"] for column in inspector.get_columns(table.name))


def _require_supported_table(connection: Connection, inspector: Any, table: Table, available: set[str]) -> None:
    _require_known_shape(inspector, table)
    _require_no_dependencies(connection, inspector, table, available)
    for column in table.primary_key.columns:
        if connection.execute(select(column).where(column.is_(None)).limit(1)).first() is not None:
            _refuse(table, "null_identity")
    if _replacement_name(table) in available:
        _refuse(table, "replacement_collision")


def _require_known_shape(inspector: Any, table: Table) -> None:
    expected_key = tuple(table.primary_key.columns.keys())
    actual_key = tuple(inspector.get_pk_constraint(table.name).get("constrained_columns") or ())
    if expected_key != actual_key:
        _refuse(table, "primary_key")
    columns = {column["name"] for column in inspector.get_columns(table.name)}
    if columns - set(table.columns.keys()):
        _refuse(table, "custom_columns")
    expected_indexes = {index.name for index in table.indexes}
    if any(index["name"] not in expected_indexes for index in inspector.get_indexes(table.name)):
        _refuse(table, "custom_indexes")


def _require_no_dependencies(connection: Connection, inspector: Any, table: Table, available: set[str]) -> None:
    triggers = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = :table"), {"table": table.name}
    ).first()
    if triggers is not None or inspector.get_foreign_keys(table.name):
        _refuse(table, "custom_dependencies")
    for other in available:
        if any(key["referred_table"] == table.name for key in inspector.get_foreign_keys(other)):
            _refuse(table, "referenced_identity")


def _replace_table(connection: Connection, table: Table) -> None:
    retained = Table(table.name, MetaData(), autoload_with=connection)
    replacement = retained.to_metadata(MetaData(), name=_replacement_name(table))
    for column in replacement.primary_key.columns:
        column.nullable = False
    connection.execute(CreateTable(replacement))
    names = list(retained.columns.keys())
    connection.execute(replacement.insert().from_select(names, select(*retained.columns), include_defaults=False))
    connection.execute(DropTable(retained))
    quote = connection.dialect.identifier_preparer.quote
    connection.exec_driver_sql(f"ALTER TABLE {quote(replacement.name)} RENAME TO {quote(table.name)}")
    for index in retained.indexes:
        index.create(connection, checkfirst=True)


def _replacement_name(table: Table) -> str:
    return f"_lotus_identity_upgrade_{table.name}"


def _refuse(table: Table, reason: str) -> None:
    raise DurableSchemaMigrationRequiredError([f"sqlite_identity_upgrade:{table.name}.{reason}"])
