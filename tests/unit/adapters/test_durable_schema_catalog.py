from __future__ import annotations

import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    event,
)

from app.adapters.durable_schema.catalog import require_metadata_schema
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError


@pytest.fixture
def schema():
    metadata = MetaData()
    parent = Table("parent", metadata, Column("id", String(36), primary_key=True))
    child = Table(
        "child",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("owner_id", ForeignKey(parent.c.id, ondelete="CASCADE"), nullable=False),
        Column("sequence", Integer, nullable=False),
    )
    Index("uq_child_owner_sequence", child.c.owner_id, child.c.sequence, unique=True)
    return metadata


@pytest.fixture
def engine():
    database = create_engine("sqlite://")
    try:
        yield database
    finally:
        database.dispose()


def test_current_schema_accepts_without_catalog_or_data_mutation(schema, engine):
    schema.create_all(engine)
    with engine.begin() as connection:
        connection.execute(schema.tables["parent"].insert().values(id="retained-owner"))
    statements = []
    event.listen(engine, "before_cursor_execute", lambda _, __, sql, *args: statements.append(sql))

    with engine.connect() as connection:
        require_metadata_schema(connection, schema)
        assert connection.execute(schema.tables["parent"].select()).one().id == "retained-owner"

    assert statements
    assert all(
        not sql.lstrip().upper().startswith(("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE"))
        for sql in statements
    )


def test_empty_database_refuses_without_creating_schema(schema, engine):
    with engine.connect() as connection:
        with pytest.raises(DurableSchemaMigrationRequiredError, match="DURABLE_SCHEMA_MIGRATION_REQUIRED"):
            require_metadata_schema(connection, schema)
        assert connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all() == []


@pytest.mark.parametrize(
    "definition, expected",
    [
        ("id VARCHAR(36) NOT NULL PRIMARY KEY, owner_id VARCHAR(36) NOT NULL", "column:child.sequence"),
        (
            "id VARCHAR(36) NOT NULL PRIMARY KEY, owner_id VARCHAR(36) NOT NULL, sequence TEXT NOT NULL",
            "column:child.sequence",
        ),
        (
            "id VARCHAR(36) NOT NULL PRIMARY KEY, owner_id VARCHAR(36) NOT NULL, sequence INTEGER",
            "column:child.sequence",
        ),
        (
            "id VARCHAR(35) NOT NULL PRIMARY KEY, owner_id VARCHAR(36) NOT NULL, sequence INTEGER NOT NULL",
            "column:child.id",
        ),
        ("id VARCHAR(36) NOT NULL, owner_id VARCHAR(36) NOT NULL, sequence INTEGER NOT NULL", "primary_key:child"),
        (
            "id VARCHAR(36) NOT NULL PRIMARY KEY, owner_id VARCHAR(36) NOT NULL, sequence INTEGER NOT NULL",
            "foreign_key:child",
        ),
    ],
)
def test_incompatible_column_or_identity_refuses(schema, engine, definition, expected):
    schema.tables["parent"].create(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE TABLE child ({definition})")
        with pytest.raises(DurableSchemaMigrationRequiredError) as error:
            require_metadata_schema(connection, schema)
    assert expected in error.value.issues
    assert "make migration-apply" in str(error.value)


@pytest.mark.parametrize(
    "replacement",
    [
        "CREATE INDEX uq_child_owner_sequence ON child (owner_id, sequence)",
        "CREATE UNIQUE INDEX uq_child_owner_sequence ON child (sequence, owner_id)",
        "CREATE UNIQUE INDEX uq_child_owner_sequence ON child (owner_id, sequence) WHERE sequence > 0",
    ],
)
def test_same_named_weakened_index_is_not_schema_evidence(schema, engine, replacement):
    schema.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX uq_child_owner_sequence")
        connection.exec_driver_sql(replacement)
        with pytest.raises(DurableSchemaMigrationRequiredError) as error:
            require_metadata_schema(connection, schema)
    assert "index:child.uq_child_owner_sequence" in error.value.issues


def test_named_error_does_not_disclose_database_or_retained_values(schema, engine):
    with engine.connect() as connection:
        with pytest.raises(DurableSchemaMigrationRequiredError) as error:
            require_metadata_schema(connection, schema)
    assert error.value.code == "DURABLE_SCHEMA_MIGRATION_REQUIRED"
    assert "sqlite" not in str(error.value)
    assert "retained-owner" not in str(error.value)


def test_mapped_complete_durable_schema_accepts_after_governed_owner(tmp_path):
    from app.adapters.composite_materialization_records import MaterializationBase
    from app.services.async_result_store import Base as ResultBase
    from app.services.composite_metadata_store import Base as CompositeBase
    from app.services.compute_job_store import Base as ComputeBase
    from app.services.execution_registry import Base as ExecutionBase
    from app.services.lineage_metadata_store import Base as LineageBase
    from app.services.source_correction_store import Base as CorrectionBase
    from scripts.durable_schema_apply import apply_durable_schema

    database_url = f"sqlite:///{tmp_path / 'owned.db'}"
    assert apply_durable_schema(database_url=database_url).status == "passed"
    database = create_engine(database_url)
    try:
        with database.connect() as connection:
            for base in (
                ExecutionBase,
                ComputeBase,
                ResultBase,
                LineageBase,
                CompositeBase,
                CorrectionBase,
                MaterializationBase,
            ):
                require_metadata_schema(connection, base.metadata)
    finally:
        database.dispose()


@pytest.mark.parametrize(
    "predicate", ["sequence >= 0", "sequence >= 1 OR sequence <= 3", "CASE WHEN sequence > 0 THEN 1 ELSE 0 END = 1"]
)
def test_same_named_changed_check_refuses_without_repair(engine, predicate):
    metadata = MetaData()
    Table(
        "bounded",
        metadata,
        Column("sequence", Integer, nullable=False),
        CheckConstraint("sequence >= 1 AND sequence <= 3", name="ck_sequence"),
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE bounded (sequence INTEGER NOT NULL, CONSTRAINT ck_sequence CHECK ({predicate}))"
        )
        with pytest.raises(DurableSchemaMigrationRequiredError) as error:
            require_metadata_schema(connection, metadata)
    assert "check:bounded.ck_sequence" in error.value.issues


@pytest.mark.parametrize("default", [None, "2"])
def test_required_constant_default_cannot_be_missing_or_changed(engine, default):
    metadata = MetaData()
    Table("numbered", metadata, Column("sequence", Integer, nullable=False, server_default="1"))
    suffix = "" if default is None else f" DEFAULT {default}"
    with engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE TABLE numbered (sequence INTEGER NOT NULL{suffix})")
        with pytest.raises(DurableSchemaMigrationRequiredError) as error:
            require_metadata_schema(connection, metadata)
    assert "default:numbered.sequence" in error.value.issues


@pytest.mark.parametrize(
    "extra", ["optional TEXT", "defaulted TEXT NOT NULL DEFAULT 'known'", "required TEXT NOT NULL"]
)
def test_unmapped_columns_must_not_block_source_owned_inserts(engine, extra):
    metadata = MetaData()
    table = Table("extendable", metadata, Column("id", Integer, primary_key=True))
    with engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE TABLE extendable (id INTEGER NOT NULL PRIMARY KEY, {extra})")
        if extra.startswith("required"):
            with pytest.raises(DurableSchemaMigrationRequiredError) as error:
                require_metadata_schema(connection, metadata)
            assert "unexpected_required_column:extendable.required" in error.value.issues
        else:
            require_metadata_schema(connection, metadata)
            connection.execute(table.insert().values(id=1))


@pytest.mark.parametrize("timezone", [True, False])
def test_postgres_timestamp_timezone_is_material_schema_identity(timezone):
    from app.adapters.durable_schema.catalog import _column_matches

    expected = Column("created_at", DateTime(timezone=True), nullable=False)
    actual = {"nullable": False, "type": DateTime(timezone=timezone)}
    assert _column_matches(actual, expected, "postgresql") is timezone


@pytest.mark.parametrize("actual_default", ["'known'", "'other'"])
def test_string_default_requires_exact_declared_value(engine, actual_default):
    from sqlalchemy import text

    metadata = MetaData()
    Table("labelled", metadata, Column("label", String(32), nullable=False, server_default=text("'known'")))
    with engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE TABLE labelled (label VARCHAR(32) NOT NULL DEFAULT {actual_default})")
        if actual_default == "'known'":
            require_metadata_schema(connection, metadata)
        else:
            with pytest.raises(DurableSchemaMigrationRequiredError, match="default:labelled.label"):
                require_metadata_schema(connection, metadata)


def test_missing_unique_constraint_and_extra_unique_index_are_not_interchangeable(engine):
    metadata = MetaData()
    Table("identified", metadata, Column("id", Integer, nullable=False), UniqueConstraint("id", name="uq_identity"))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE identified (id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE UNIQUE INDEX unrelated_unique ON identified (id)")
        with pytest.raises(DurableSchemaMigrationRequiredError) as error:
            require_metadata_schema(connection, metadata)
        assert error.value.issues == (
            "unexpected_unique_index:identified.unrelated_unique",
            "unique_constraint:identified",
        )


def test_postgres_unvalidated_constraints_and_unready_indexes_refuse_only_owned_catalogue_entries():
    from types import SimpleNamespace

    from app.adapters.durable_schema.catalog import _postgres_catalog_issues

    metadata = MetaData()
    table = Table("owned", metadata, Column("id", Integer, primary_key=True))
    Index("ix_owned_id", table.c.id)
    queries = []

    def execute(statement):
        sql = str(statement)
        queries.append(sql)
        assert sql.startswith("SELECT ") and "current_schema()" in sql
        if "FROM pg_constraint" in sql:
            assert "NOT k.convalidated" in sql
            return [("owned", "ck_owned"), ("foreign_table", "ck_foreign")]
        assert "NOT k.indisvalid OR NOT k.indisready OR NOT k.indislive" in sql
        return [("owned", "ix_owned_id"), ("owned", "ix_extension"), ("foreign_table", "ix_foreign")]

    connection = SimpleNamespace(execute=execute)
    assert _postgres_catalog_issues(connection, metadata) == [
        "unvalidated_constraint:owned.ck_owned",
        "invalid_index:owned.ix_owned_id",
    ]
    assert len(queries) == 2
