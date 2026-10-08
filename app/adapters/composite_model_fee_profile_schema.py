"""Fenced schema-owner catalog creation; runtime verification performs no DDL."""

from sqlalchemy import MetaData, inspect, select
from sqlalchemy.engine.interfaces import Dialect

from app.adapters.composite_model_fee_profile_records import ModelFeeProfileBase
from app.adapters.durable_schema.catalog import require_metadata_schema
from app.adapters.durable_schema.statements import SchemaStatements

_TABLE = "composite_model_fee_profiles"
_TRIGGER = "trg_model_fee_profiles_immutable"
_FUNCTION = "reject_model_fee_profile_mutation"


def require_model_fee_profile_schema(connection):
    if inspect(connection).has_table(_TABLE):
        require_metadata_schema(connection, ModelFeeProfileBase.metadata)


def create_model_fee_profile_schema(connection):
    ModelFeeProfileBase.metadata.create_all(connection)
    for statement in model_fee_profile_guard_statements(connection.dialect):
        connection.exec_driver_sql(statement)


def rollback_empty_model_fee_profile_catalog(engine):
    """Explicit owner rollback refuses destruction of any retained method input."""
    from app.services.durable_schema_creation import create_durable_schema

    create_durable_schema(engine, MetaData(), schema_preflights=(_drop_empty_catalog,))


def _drop_empty_catalog(connection):
    if not inspect(connection).has_table(_TABLE):
        return
    require_model_fee_profile_schema(connection)
    if connection.dialect.name == "postgresql":
        # Serialize the count and drop against concurrent publication, including
        # writers that do not acquire the schema-owner advisory lock.
        connection.exec_driver_sql(f"LOCK TABLE {_TABLE} IN ACCESS EXCLUSIVE MODE")
    table = ModelFeeProfileBase.metadata.tables[_TABLE]
    if connection.execute(select(table.c.tenant_id).limit(1)).first() is not None:
        raise RuntimeError("Catalog rollback refuses loss of retained model-fee profile content")
    table.drop(connection)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {_FUNCTION}()")


def model_fee_profile_guard_statements(dialect: Dialect) -> tuple[str, ...]:
    writer = SchemaStatements(dialect)
    if dialect.name == "sqlite":
        _sqlite_guards(writer)
    elif dialect.name == "postgresql":
        _postgres_guards(writer)
    return tuple(writer.statements)


def _sqlite_guards(writer):
    for operation in ("UPDATE", "DELETE"):
        writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {_TRIGGER}_{operation.lower()}")
        writer.exec_driver_sql(
            f"CREATE TRIGGER {_TRIGGER}_{operation.lower()} BEFORE {operation} ON {_TABLE} BEGIN SELECT RAISE(ABORT, 'model fee profile content is immutable'); END"
        )


def _postgres_guards(writer):
    writer.exec_driver_sql(f"""CREATE OR REPLACE FUNCTION {_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'model fee profile content is immutable'; END; $$""")
    for operation in ("UPDATE", "DELETE"):
        name = f"{_TRIGGER}_{operation.lower()}"
        writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {_TABLE}")
        writer.exec_driver_sql(
            f"CREATE TRIGGER {name} BEFORE {operation} ON {_TABLE} FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}()"
        )
    name = f"{_TRIGGER}_truncate"
    writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {_TABLE}")
    writer.exec_driver_sql(
        f"CREATE TRIGGER {name} BEFORE TRUNCATE ON {_TABLE} FOR EACH STATEMENT EXECUTE FUNCTION {_FUNCTION}()"
    )
