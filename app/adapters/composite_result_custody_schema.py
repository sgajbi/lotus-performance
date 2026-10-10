"""Purpose-scoped original result protection in the existing async result table.

The schema owner installs these guards. Runtime verification never repairs them.
Ordinary analytic results retain their existing mutation and retention behavior.
"""

from sqlalchemy.engine.interfaces import Dialect

from app.adapters.durable_schema.statements import SchemaStatements
from app.services.analytics_workflow_types import (
    ANALYTICS_WORKFLOW_COMPOSITE_ATTRIBUTION,
    ANALYTICS_WORKFLOW_COMPOSITE_POOLED_MWR,
)

COMPOSITE_CAPTURE_ANALYTICS_TYPE = "COMPOSITE_TWR_CANDIDATE"
COMPOSITE_POOLED_ANALYTICS_TYPE = ANALYTICS_WORKFLOW_COMPOSITE_POOLED_MWR
COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE = ANALYTICS_WORKFLOW_COMPOSITE_ATTRIBUTION
COMPOSITE_PROTECTED_RESULT_TYPES = (
    COMPOSITE_CAPTURE_ANALYTICS_TYPE,
    COMPOSITE_POOLED_ANALYTICS_TYPE,
    COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE,
)
_TABLE = "analytics_async_result"
_TRIGGER = "trg_composite_result_custody"
_FUNCTION = "reject_composite_result_custody_mutation"


def create_composite_result_custody_guards(connection):
    for statement in composite_result_custody_guard_statements(connection.dialect):
        connection.exec_driver_sql(statement)


def composite_result_custody_guard_statements(dialect: Dialect) -> tuple[str, ...]:
    writer = SchemaStatements(dialect)
    protected_types = ", ".join(f"'{purpose}'" for purpose in COMPOSITE_PROTECTED_RESULT_TYPES)
    protected = f"analytics_type IN ({protected_types})"
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
        # Keep the function literal so SQL construction accepts no runtime data;
        # custody tests exercise both purposes against this catalog contract.
        writer.exec_driver_sql("""CREATE OR REPLACE FUNCTION reject_composite_result_custody_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE protected_types CONSTANT text[] := ARRAY['COMPOSITE_TWR_CANDIDATE', 'COMPOSITE_POOLED_MWR', 'COMPOSITE_ATTRIBUTION'];
            BEGIN
                IF TG_OP = 'TRUNCATE' THEN
                    IF EXISTS (SELECT 1 FROM analytics_async_result WHERE analytics_type = ANY(protected_types)) THEN
                        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'composite captured result is immutable';
                    END IF;
                    RETURN NULL;
                END IF;
                IF OLD.analytics_type = ANY(protected_types) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'composite captured result is immutable';
                END IF;
                IF TG_OP = 'UPDATE' THEN
                    IF NEW.analytics_type = ANY(protected_types) THEN
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
