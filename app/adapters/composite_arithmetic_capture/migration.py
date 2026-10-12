"""Owner-only paired nullable expansion; legacy immutable rows remain absent."""

from sqlalchemy import inspect
from sqlalchemy.schema import MetaData

from app.adapters.composite_result_candidate_records import CandidateBase, CompositeResultCandidateModel
from app.adapters.durable_schema.catalog import require_metadata_schema
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.adapters.durable_schema.guards import require_managed_guards

COLUMNS = ("arithmetic_capture_json", "arithmetic_capture_digest")


def upgrade_candidate_capture_columns(connection):
    from app.adapters.composite_result_candidate_schema import candidate_guard_statements

    inspector = inspect(connection)
    table = CompositeResultCandidateModel.__table__
    if not inspector.has_table(table.name):
        return
    present = {item["name"] for item in inspector.get_columns(table.name)}
    missing = set(COLUMNS) - present
    if not missing:
        require_metadata_schema(connection, CandidateBase.metadata)
        return
    if missing != set(COLUMNS):
        raise DurableSchemaMigrationRequiredError(["candidate_capture_half_upgrade"])
    legacy = table.to_metadata(MetaData())
    for name in COLUMNS:
        legacy._columns.remove(legacy.c[name])
    require_metadata_schema(connection, legacy.metadata)
    require_managed_guards(connection, candidate_guard_statements(connection.dialect, include_capture=False))
    connection.exec_driver_sql("ALTER TABLE composite_result_candidates ADD COLUMN arithmetic_capture_json TEXT NULL")
    connection.exec_driver_sql(
        "ALTER TABLE composite_result_candidates ADD COLUMN arithmetic_capture_digest VARCHAR(71) NULL"
    )
    require_metadata_schema(connection, CandidateBase.metadata)
