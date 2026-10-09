"""Owner-only expansion of the exact immutable periodic-fee catalog.

Retained JSON, publisher, digest and identity remain byte-for-byte unchanged.
Runtime verification never invokes this transactional owner migration.
"""

from sqlalchemy import CheckConstraint, MetaData, inspect, select, text
from sqlalchemy.schema import CreateTable

from app.adapters.composite_model_fee_profile_records import CompositeModelFeeProfileModel
from app.adapters.composite_model_fee_profile_schema import (
    model_fee_profile_guard_statements,
    require_model_fee_profile_schema,
)
from app.adapters.durable_schema.catalog import require_metadata_schema
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.adapters.durable_schema.guards import require_managed_guards
from app.adapters.durable_schema.predicates import predicate_identity

_TABLE = CompositeModelFeeProfileModel.__tablename__
_GUARD = "ck_model_fee_profile_product"
_LEGACY = "product_name = 'CompositePeriodicModelFeeProfile' AND product_version = 'v1'"
_SCHEDULED_LEGACY = "product_name IN ('CompositePeriodicModelFeeProfile', 'CompositeScheduledModelFeeProfile') AND product_version = 'v1'"
_REPLACEMENT = "_lotus_model_fee_catalog_upgrade"


def upgrade_model_fee_profile_products(connection):
    inspector = inspect(connection)
    if not inspector.has_table(_TABLE):
        return
    guards = {row["name"]: row["sqltext"] for row in inspector.get_check_constraints(_TABLE)}
    legacy = _legacy_product_guard(guards)
    if not legacy:
        require_model_fee_profile_schema(connection)
        return
    _require_known_legacy(connection, guards, legacy)
    if connection.dialect.name == "postgresql":
        _expand_postgres(connection)
    elif connection.dialect.name == "sqlite":
        _replace_sqlite(connection)
    else:
        _refuse("unsupported dialect")
    require_model_fee_profile_schema(connection)
    require_managed_guards(connection, model_fee_profile_guard_statements(connection.dialect))


def _legacy_product_guard(guards):
    context = {"text_columns": {"product_name", "product_version"}}
    try:
        return next(
            (
                candidate
                for candidate in (_LEGACY, _SCHEDULED_LEGACY)
                if predicate_identity(guards.get(_GUARD, ""), **context) == predicate_identity(candidate, **context)
            ),
            None,
        )
    except ValueError:
        return None


def _metadata_with_product_guard(predicate, dialect):
    metadata = MetaData()
    table = CompositeModelFeeProfileModel.__table__.to_metadata(metadata)
    _remove_other_dialect_checks(table, dialect)
    table.constraints.remove(_check_named(table, _GUARD))
    table.append_constraint(CheckConstraint(predicate, name=_GUARD))
    return metadata


def _check_named(table, name):
    return next(item for item in table.constraints if isinstance(item, CheckConstraint) and item.name == name)


def _remove_other_dialect_checks(table, dialect):
    # SQLAlchemy table cloning does not retain conditional DDL. Remove the
    # other dialect's tenant predicate explicitly before compiling any clone.
    for original in CompositeModelFeeProfileModel.__table__.constraints:
        conditional = original._ddl_if
        if isinstance(original, CheckConstraint) and conditional and conditional.dialect != dialect:
            for copied in list(table.constraints):
                if isinstance(copied, CheckConstraint) and str(copied.sqltext) == str(original.sqltext):
                    table.constraints.remove(copied)


def _require_known_legacy(connection, guards, legacy):
    inspector = inspect(connection)
    require_metadata_schema(connection, _metadata_with_product_guard(legacy, connection.dialect.name))
    require_managed_guards(connection, model_fee_profile_guard_statements(connection.dialect))
    expected_checks = {"ck_model_fee_profile_tenant", _GUARD, "ck_model_fee_profile_digest"}
    expected_columns = set(CompositeModelFeeProfileModel.__table__.columns.keys())
    if set(guards) != expected_checks or {row["name"] for row in inspector.get_columns(_TABLE)} != expected_columns:
        _refuse("unknown columns or checks")
    _require_replaceable_table(inspector)
    _require_known_dependencies(connection, inspector)


def _require_replaceable_table(inspector):
    extra_indexes = [row for row in inspector.get_indexes(_TABLE) if not row.get("duplicates_constraint")]
    if inspector.has_table(_REPLACEMENT) or extra_indexes or inspector.get_foreign_keys(_TABLE):
        _refuse("replacement collision, indexes or foreign keys")


def _require_known_dependencies(connection, inspector):
    _require_no_relational_dependencies(inspector)
    _require_known_triggers(connection)


def _require_no_relational_dependencies(inspector):
    for other in inspector.get_table_names():
        if any(key["referred_table"] == _TABLE for key in inspector.get_foreign_keys(other)):
            _refuse("incoming foreign key")
    for view in inspector.get_view_names():
        definition = inspector.get_view_definition(view) or ""
        # SQLite resolves both quoted and unquoted identifiers without case
        # sensitivity. Detect those dependencies before any replacement DDL.
        if inspector.bind.dialect.name == "sqlite":
            definition = definition.casefold()
        if _TABLE in definition:
            _refuse("view dependency")


def _require_known_triggers(connection):
    if connection.dialect.name == "sqlite":
        names = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=:table"), {"table": _TABLE}
            ).scalars()
        )
        expected = {"trg_model_fee_profiles_immutable_update", "trg_model_fee_profiles_immutable_delete"}
    else:
        names = set(
            connection.execute(
                text(
                    "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=:table AND NOT t.tgisinternal"
                ),
                {"table": _TABLE},
            ).scalars()
        )
        expected = {
            "trg_model_fee_profiles_immutable_update",
            "trg_model_fee_profiles_immutable_delete",
            "trg_model_fee_profiles_immutable_truncate",
        }
    if names != expected:
        _refuse("unknown trigger dependency")


def _expand_postgres(connection):
    predicate = _current_product_predicate()
    connection.exec_driver_sql(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_GUARD}")
    connection.exec_driver_sql(f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_GUARD} CHECK ({predicate})")


def _current_product_predicate():
    return next(
        str(item.sqltext)
        for item in CompositeModelFeeProfileModel.__table__.constraints
        if isinstance(item, CheckConstraint) and item.name == _GUARD
    )


def _replace_sqlite(connection):
    retained = CompositeModelFeeProfileModel.__table__
    current = _metadata_with_product_guard(_current_product_predicate(), "sqlite").tables[_TABLE]
    replacement = current.to_metadata(MetaData(), name=_REPLACEMENT)
    connection.execute(CreateTable(replacement))
    names = list(retained.columns.keys())
    connection.execute(replacement.insert().from_select(names, select(*retained.columns), include_defaults=False))
    connection.exec_driver_sql(f"DROP TABLE {_TABLE}")
    connection.exec_driver_sql(f"ALTER TABLE {_REPLACEMENT} RENAME TO {_TABLE}")
    for statement in model_fee_profile_guard_statements(connection.dialect):
        connection.exec_driver_sql(statement)


def _refuse(reason):
    raise DurableSchemaMigrationRequiredError(["model_fee_catalog_upgrade:" + reason])
