"""Purpose-scoped original result protection in the existing async result table.

The schema owner installs these guards. Runtime verification never repairs them.
Ordinary analytic results retain their existing mutation and retention behavior.
"""

from sqlalchemy.engine.interfaces import Dialect

from app.adapters.durable_schema.statements import SchemaStatements

COMPOSITE_CAPTURE_ANALYTICS_TYPE = "COMPOSITE_TWR_CANDIDATE"
_TABLE = "analytics_async_result"
_TRIGGER = "trg_composite_result_custody"
_FUNCTION = "reject_composite_result_custody_mutation"


def create_composite_result_custody_guards(connection):
    for statement in composite_result_custody_guard_statements(connection.dialect):
        connection.exec_driver_sql(statement)


def composite_result_custody_guard_statements(dialect: Dialect) -> tuple[str, ...]:
    writer = SchemaStatements(dialect)
    protected = f"analytics_type = '{COMPOSITE_CAPTURE_ANALYTICS_TYPE}'"
    if dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            name = f"{_TRIGGER}_{operation.lower()}"
            condition = f"OLD.{protected}"
            if operation == "UPDATE":
                condition += f" OR NEW.{protected}"
            writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
            writer.exec_driver_sql(
                f"CREATE TRIGGER {name} BEFORE {operation} ON {_TABLE} WHEN {condition} "
                "BEGIN SELECT RAISE(ABORT, 'composite captured result is immutable'); END"
            )
    elif dialect.name == "postgresql":
        # TRUNCATE has no OLD/NEW row. Test it before accessing either record.
        writer.exec_driver_sql("""CREATE OR REPLACE FUNCTION reject_composite_result_custody_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'TRUNCATE' THEN
                    IF EXISTS (SELECT 1 FROM analytics_async_result WHERE analytics_type = 'COMPOSITE_TWR_CANDIDATE') THEN
                        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'composite captured result is immutable';
                    END IF;
                    RETURN NULL;
                END IF;
                IF OLD.analytics_type = 'COMPOSITE_TWR_CANDIDATE' THEN
                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'composite captured result is immutable';
                END IF;
                IF TG_OP = 'UPDATE' THEN
                    IF NEW.analytics_type = 'COMPOSITE_TWR_CANDIDATE' THEN
                        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'composite captured result is immutable';
                    END IF;
                    RETURN NEW;
                END IF;
                RETURN OLD;
            END; $$""")
        for operation, level in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
            name = f"{_TRIGGER}_{operation.lower()}"
            writer.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {_TABLE}")
            writer.exec_driver_sql(
                f"CREATE TRIGGER {name} BEFORE {operation} ON {_TABLE} FOR EACH {level} EXECUTE FUNCTION {_FUNCTION}()"
            )
    return tuple(writer.statements)
