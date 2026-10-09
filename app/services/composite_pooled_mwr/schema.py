"""Source-owned immutable input custody; schema creation is an explicit owner action."""

from sqlalchemy import Column, MetaData, String, Table, Text, inspect
from sqlalchemy.engine import Connection

from app.adapters.durable_schema.catalog import require_metadata_schema
from app.adapters.durable_schema.guards import require_managed_guards

metadata = MetaData()
pooled_inputs = Table(
    "composite_pooled_mwr_inputs",
    metadata,
    Column("tenant_id", String(255), primary_key=True),
    Column("calculation_id", String(36), primary_key=True),
    Column("input_manifest_digest", String(255), nullable=False),
    Column("payload_digest", String(255), nullable=False),
    Column("payload_json", Text, nullable=False),
)


def immutable_guards(dialect: str) -> tuple[str, ...]:
    table = pooled_inputs.name
    if dialect == "sqlite":
        return tuple(
            f"CREATE TRIGGER {table}_{operation.lower()} BEFORE {operation} ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'pooled input custody is immutable'); END"
            for operation in ("UPDATE", "DELETE")
        )
    if dialect == "postgresql":
        function = f"{table}_immutable"
        return (
            f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$"
            "BEGIN RAISE EXCEPTION 'pooled input custody is immutable'; END;$$;",
            *(
                f"CREATE TRIGGER {table}_{operation.lower()} BEFORE {operation} ON {table} "
                f"FOR EACH {'STATEMENT' if operation == 'TRUNCATE' else 'ROW'} "
                f"EXECUTE FUNCTION {function}();"
                for operation in ("UPDATE", "DELETE", "TRUNCATE")
            ),
        )
    raise ValueError("Pooled input custody requires PostgreSQL or SQLite.")


def preflight_schema(connection: Connection) -> None:
    """Refuse existing drift instead of repairing it as a side effect of bootstrap."""
    if inspect(connection).has_table(pooled_inputs.name):
        require_metadata_schema(connection, metadata)
        require_managed_guards(connection, immutable_guards(connection.dialect.name))


def install_guards(connection: Connection) -> None:
    statements = immutable_guards(connection.dialect.name)
    # The preflight verified existing installations. Only a newly created table
    # lacks guards; creation and installation share the owner's transaction.
    inspector = inspect(connection)
    if connection.dialect.name == "sqlite":
        installed = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='composite_pooled_mwr_inputs'"
        ).fetchall()
    else:
        installed = connection.exec_driver_sql(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() "
            "AND c.relname='composite_pooled_mwr_inputs' AND NOT t.tgisinternal"
        ).fetchall()
    if inspector.has_table(pooled_inputs.name) and not installed:
        for statement in statements:
            connection.exec_driver_sql(statement)
    require_managed_guards(connection, statements)
