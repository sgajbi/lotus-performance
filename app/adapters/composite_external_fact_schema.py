"""Owner-invoked migration retaining internal facts and relational constraints."""

from sqlalchemy import CheckConstraint, MetaData, Table, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateTable, DropTable

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.adapters.durable_schema.predicates import predicate_identity

INTERNAL_EVIDENCE_CHECK = (
    "source_authority_identity_json IS NOT NULL OR (ending_market_value IS NOT NULL AND calculation_id IS NOT NULL)"
)


def upgrade_external_fact_columns(connection: Connection, table: Table) -> None:
    installed = {column["name"]: column for column in inspect(connection).get_columns(table.name)}
    checks = {item["name"]: item for item in inspect(connection).get_check_constraints(table.name)}
    _require_internal_guard(checks)
    if _is_current_schema(installed, checks):
        return
    if connection.dialect.name == "postgresql":
        _upgrade_postgres(connection, checks)
        return
    if connection.dialect.name != "sqlite":
        raise DurableSchemaMigrationRequiredError(["external_facts:unsupported_dialect"])
    _upgrade_sqlite(connection, table, installed, checks)


def _require_internal_guard(checks):
    existing_guard = checks.get("ck_composite_fact_internal_evidence")
    if existing_guard is not None and predicate_identity(existing_guard["sqltext"]) != predicate_identity(
        INTERNAL_EVIDENCE_CHECK
    ):
        raise DurableSchemaMigrationRequiredError(["external_facts:weakened_internal_guard"])


def _is_current_schema(installed, checks):
    return (
        "source_authority_identity_json" in installed
        and all(installed[key]["nullable"] for key in ("ending_market_value", "calculation_id"))
        and "ck_composite_fact_internal_evidence" in checks
    )


def _upgrade_postgres(connection, checks):
    connection.exec_driver_sql(
        "ALTER TABLE composite_member_return_facts ADD COLUMN IF NOT EXISTS source_authority_identity_json TEXT"
    )
    for column in ("ending_market_value", "calculation_id"):
        connection.exec_driver_sql(f"ALTER TABLE composite_member_return_facts ALTER COLUMN {column} DROP NOT NULL")
    if "ck_composite_fact_internal_evidence" not in checks:
        connection.exec_driver_sql(
            "ALTER TABLE composite_member_return_facts ADD CONSTRAINT ck_composite_fact_internal_evidence "
            f"CHECK ({INTERNAL_EVIDENCE_CHECK})"
        )


def _require_sqlite_shape(connection, table, installed):
    inspector = inspect(connection)
    if set(installed) - set(table.columns.keys()):
        raise DurableSchemaMigrationRequiredError(["external_facts:unknown_columns"])
    for name in inspector.get_table_names():
        if any(key["referred_table"] == table.name for key in inspector.get_foreign_keys(name)):
            raise DurableSchemaMigrationRequiredError(["external_facts:referenced_table"])
    triggers = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=:table"), {"table": table.name}
    ).first()
    if triggers is not None:
        raise DurableSchemaMigrationRequiredError(["external_facts:unexpected_trigger"])
    if "_lotus_external_fact_upgrade" in inspector.get_table_names():
        raise DurableSchemaMigrationRequiredError(["external_facts:replacement_collision"])


def _upgrade_sqlite(connection, table, installed, checks):
    _require_sqlite_shape(connection, table, installed)
    retained = Table(table.name, MetaData(), autoload_with=connection)
    replacement_name = "_lotus_external_fact_upgrade"
    replacement = _replacement_table(retained, replacement_name, checks)
    connection.execute(CreateTable(replacement))
    names = list(retained.c.keys())
    connection.execute(replacement.insert().from_select(names, select(*retained.c), include_defaults=False))
    connection.execute(DropTable(retained))
    connection.exec_driver_sql(f"ALTER TABLE {replacement_name} RENAME TO composite_member_return_facts")
    for index in retained.indexes:
        index.create(connection, checkfirst=True)


def _replacement_table(retained, replacement_name, checks):
    replacement_metadata = MetaData()
    for related in retained.metadata.tables.values():
        if related.name != retained.name:
            related.to_metadata(replacement_metadata)
    replacement = retained.to_metadata(replacement_metadata, name=replacement_name)
    for key in ("ending_market_value", "calculation_id"):
        replacement.c[key].nullable = True
    if "source_authority_identity_json" not in replacement.c:
        from sqlalchemy import Column, Text

        replacement.append_column(Column("source_authority_identity_json", Text, nullable=True))
    if "ck_composite_fact_internal_evidence" not in checks:
        replacement.append_constraint(
            CheckConstraint(
                INTERNAL_EVIDENCE_CHECK,
                name="ck_composite_fact_internal_evidence",
            )
        )
    return replacement
