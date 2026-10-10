"""Subordinate immutable input custody installed by CompositeMetadataStore."""

from sqlalchemy import Column, MetaData, String, Table, Text, inspect

from app.adapters.durable_schema.catalog import require_metadata_schema
from app.adapters.durable_schema.guards import require_managed_guards
from app.adapters.durable_schema.statements import SchemaStatements

metadata = MetaData()
attribution_inputs = Table(
    "composite_attribution_inputs",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("calculation_id", String(36), primary_key=True),
    Column("input_manifest_digest", String(71), nullable=False),
    Column("payload_digest", String(71), nullable=False),
    Column("payload_json", Text, nullable=False),
)


def attribution_guard_statements(dialect):
    writer = SchemaStatements(dialect)
    if dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            writer.exec_driver_sql(
                f"CREATE TRIGGER composite_attribution_inputs_{operation.lower()} BEFORE {operation} ON composite_attribution_inputs BEGIN SELECT RAISE(ABORT, 'attribution input custody is immutable'); END"
            )
    elif dialect.name == "postgresql":
        writer.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION composite_attribution_inputs_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'attribution input custody is immutable'; END;$$;"
        )
        for operation, level in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
            writer.exec_driver_sql(
                f"CREATE TRIGGER composite_attribution_inputs_{operation.lower()} BEFORE {operation} ON composite_attribution_inputs FOR EACH {level} EXECUTE FUNCTION composite_attribution_inputs_immutable();"
            )
    else:
        raise ValueError("Attribution custody requires PostgreSQL or SQLite.")
    return tuple(writer.statements)


def verify_attribution_schema(connection):
    require_metadata_schema(connection, metadata)
    require_managed_guards(connection, attribution_guard_statements(connection.dialect))


def require_attribution_schema(connection):
    if inspect(connection).has_table(attribution_inputs.name):
        verify_attribution_schema(connection)


def create_attribution_schema(connection):
    if inspect(connection).has_table(attribution_inputs.name):
        verify_attribution_schema(connection)
        return
    metadata.create_all(connection)
    for statement in attribution_guard_statements(connection.dialect):
        connection.exec_driver_sql(statement)
    verify_attribution_schema(connection)
