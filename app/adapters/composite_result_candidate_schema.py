"""Owner-installed descriptor guards; no result table is created by this owner."""

from sqlalchemy import inspect

from app.adapters.composite_result_candidate_records import CandidateBase
from app.adapters.durable_schema.catalog import require_metadata_schema
from app.adapters.durable_schema.statements import SchemaStatements

_TABLE = "composite_result_candidates"
_FUNCTION = "reject_composite_result_candidate_mutation"
_TRIGGER = "trg_composite_result_candidate_immutable"


def require_candidate_schema(connection):
    if inspect(connection).has_table(_TABLE):
        require_metadata_schema(connection, CandidateBase.metadata)


def create_candidate_schema(connection):
    CandidateBase.metadata.create_all(connection)
    for statement in candidate_guard_statements(connection.dialect):
        connection.exec_driver_sql(statement)


def candidate_guard_statements(dialect):
    writer = SchemaStatements(dialect)
    original = (
        "SELECT 1 FROM analytics_async_result r WHERE r.calculation_id = NEW.calculation_id "
        "AND r.tenant_id = NEW.tenant_id "
        "AND r.analytics_type = 'COMPOSITE_TWR_CANDIDATE' "
        "AND r.result_status = 'complete' AND r.response_json IS NOT NULL "
        "AND r.error_message IS NULL AND r.error_type IS NULL AND r.failure_json IS NULL"
    )
    if dialect.name == "sqlite":
        name = "trg_composite_result_candidate_original"
        writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
        writer.exec_driver_sql(
            f"CREATE TRIGGER {name} BEFORE INSERT ON {_TABLE} WHEN NOT EXISTS ({original}) BEGIN SELECT RAISE(ABORT, 'composite candidate original result is unavailable'); END"
        )
        for operation in ("UPDATE", "DELETE"):
            name = f"{_TRIGGER}_{operation.lower()}"
            writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
            writer.exec_driver_sql(
                f"CREATE TRIGGER {name} BEFORE {operation} ON {_TABLE} BEGIN SELECT RAISE(ABORT, 'composite result candidate is immutable'); END"
            )
    elif dialect.name == "postgresql":
        function = "require_composite_result_candidate_original"
        name = "trg_composite_result_candidate_original"
        writer.exec_driver_sql(
            f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NOT EXISTS ({original}) THEN RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'composite candidate original result is unavailable'; END IF; RETURN NEW; END; $$"
        )
        writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {_TABLE}")
        writer.exec_driver_sql(
            f"CREATE TRIGGER {name} BEFORE INSERT ON {_TABLE} FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
        writer.exec_driver_sql(
            f"CREATE OR REPLACE FUNCTION {_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'composite result candidate is immutable'; END; $$"
        )
        for operation, level in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
            name = f"{_TRIGGER}_{operation.lower()}"
            writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {_TABLE}")
            writer.exec_driver_sql(
                f"CREATE TRIGGER {name} BEFORE {operation} ON {_TABLE} FOR EACH {level} EXECUTE FUNCTION {_FUNCTION}()"
            )
    return tuple(writer.statements)
