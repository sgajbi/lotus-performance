"""Explicit, additive migration for retained source custody; never run at startup."""

from sqlalchemy import MetaData, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateColumn

SOURCE_CUSTODY_COLUMNS = (
    "source_tenant_id",
    "source_attempt_id",
    "source_attempt_number",
    "source_custody_state",
    "source_root_digest",
    "source_manifest_digest",
)


def apply_source_custody_columns(connection: Connection, metadata: MetaData) -> None:
    table = metadata.tables["lineage_records"]
    existing = {column["name"] for column in inspect(connection).get_columns(table.name)}
    for name in SOURCE_CUSTODY_COLUMNS:
        if name not in existing:
            definition = str(CreateColumn(table.c[name]).compile(dialect=connection.dialect))
            connection.exec_driver_sql(f"ALTER TABLE lineage_records ADD COLUMN {definition}")
