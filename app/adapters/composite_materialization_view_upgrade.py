"""Owner-only, transactional expansion of the known populated materialization ledger.

Runtime verification never invokes this upgrade. Unknown guards or dependencies
refuse before mutation; command, source, outcomes and progress remain unchanged.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, MetaData, Table, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateTable, DropTable

from app.adapters.composite_materialization_records import CompositeMaterializationModel
from app.adapters.composite_materialization_schema import (
    CompositeMaterializationMigrationRequiredError,
    _column_issues,
    _constraint_issues,
    _expected_constraints,
    _identity_issues,
    _predicate_identity,
    require_materialization_schema,
)

_VIEW_GUARD = "ck_composite_materialization_view"
_LEGACY_VIEW = "return_view IN ('GROSS', 'NET_ACTUAL')"
_TABLE = CompositeMaterializationModel.__tablename__
_REPLACEMENT = "_lotus_model_fee_view_upgrade"


def upgrade_materialization_return_views(connection: Connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table(_TABLE):
        return
    guards = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints(_TABLE)}
    if _predicate_identity(guards.get(_VIEW_GUARD, "")) != _predicate_identity(_LEGACY_VIEW):
        require_materialization_schema(connection)
        return
    _require_known_legacy_schema(connection, guards)
    if connection.dialect.name == "postgresql":
        _upgrade_postgres(connection)
    elif connection.dialect.name == "sqlite":
        _upgrade_sqlite(connection)
    else:
        _refuse("unsupported database dialect")
    require_materialization_schema(connection)


def _require_known_legacy_schema(connection: Connection, guards: dict) -> None:
    expected = _expected_constraints(connection)
    expected[_VIEW_GUARD] = _LEGACY_VIEW
    issues = [
        *_column_issues(connection),
        *_identity_issues(connection),
        *_constraint_issues(connection, expected=expected),
    ]
    inspector = inspect(connection)
    columns = {item["name"] for item in inspector.get_columns(_TABLE)}
    if columns != set(CompositeMaterializationModel.__table__.columns.keys()) or set(guards) != set(expected):
        issues.append("unknown columns or guards")
    if issues:
        _refuse("; ".join(sorted(issues)))


def _upgrade_postgres(connection: Connection) -> None:
    # The schema owner already holds the bootstrap advisory fence. PostgreSQL
    # ALTER TABLE additionally locks this table and validates every retained row.
    predicate = _expected_constraints(connection)[_VIEW_GUARD]
    connection.exec_driver_sql(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_VIEW_GUARD}")
    connection.exec_driver_sql(f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_VIEW_GUARD} CHECK ({predicate})")


def _upgrade_sqlite(connection: Connection) -> None:
    _require_replaceable_sqlite_table(connection)
    retained = Table(_TABLE, MetaData(), autoload_with=connection)
    replacement = retained.to_metadata(MetaData(), name=_REPLACEMENT)
    guard = next(
        item for item in replacement.constraints if isinstance(item, CheckConstraint) and item.name == _VIEW_GUARD
    )
    replacement.constraints.remove(guard)
    replacement.append_constraint(CheckConstraint(_expected_constraints(connection)[_VIEW_GUARD], name=_VIEW_GUARD))
    connection.execute(CreateTable(replacement))
    names = list(retained.columns.keys())
    connection.execute(replacement.insert().from_select(names, select(*retained.columns), include_defaults=False))
    connection.execute(DropTable(retained))
    connection.exec_driver_sql(f"ALTER TABLE {_REPLACEMENT} RENAME TO {_TABLE}")


def _require_replaceable_sqlite_table(connection: Connection) -> None:
    inspector = inspect(connection)
    if inspector.has_table(_REPLACEMENT) or inspector.get_indexes(_TABLE) or inspector.get_foreign_keys(_TABLE):
        _refuse("replacement collision, indexes or foreign keys")
    dependency = connection.execute(
        text(
            "SELECT name FROM sqlite_master WHERE type IN ('trigger', 'view') AND (tbl_name = :table OR sql LIKE :reference)"
        ),
        {"table": _TABLE, "reference": f"%{_TABLE}%"},
    ).first()
    if dependency is not None:
        _refuse("custom trigger or view dependency")
    for other in inspector.get_table_names():
        if any(key["referred_table"] == _TABLE for key in inspector.get_foreign_keys(other)):
            _refuse("incoming foreign key")


def _refuse(reason: str) -> None:
    raise CompositeMaterializationMigrationRequiredError(
        "Model-fee ledger upgrade requires reviewed migration: " + reason
    )
