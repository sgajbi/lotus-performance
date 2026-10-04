from __future__ import annotations

import pytest
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, create_engine, inspect
from sqlalchemy.exc import IntegrityError

from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.adapters.durable_schema.sqlite_identity_upgrade import upgrade_sqlite_primary_key_nullability
from app.services.durable_schema_creation import create_durable_schema


@pytest.fixture
def metadata():
    metadata = MetaData()
    table = Table(
        "retained", metadata, Column("id", String(36), primary_key=True), Column("attempts", Integer, nullable=False)
    )
    Index("ix_retained_attempts", table.c.attempts)
    return metadata


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    try:
        yield engine
    finally:
        engine.dispose()


def _upgrade(database, metadata):
    create_durable_schema(
        database,
        metadata,
        schema_preflights=(lambda connection: upgrade_sqlite_primary_key_nullability(connection, metadata),),
    )


def test_supported_identity_upgrade_preserves_rows_indexes_and_restart(database, metadata):
    with database.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE retained (id VARCHAR(36) PRIMARY KEY, attempts INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE INDEX ix_retained_attempts ON retained (attempts)")
        connection.exec_driver_sql("INSERT INTO retained VALUES ('retained-identity', 3)")
    _upgrade(database, metadata)
    _upgrade(database, metadata)
    inspector = inspect(database)
    assert not inspector.get_columns("retained")[0]["nullable"]
    assert inspector.get_indexes("retained")[0]["name"] == "ix_retained_attempts"
    with database.connect() as connection:
        assert connection.exec_driver_sql("SELECT * FROM retained").one() == ("retained-identity", 3)
    with pytest.raises(IntegrityError):
        with database.begin() as connection:
            connection.exec_driver_sql("INSERT INTO retained VALUES (NULL, 4)")


@pytest.mark.parametrize(
    "obstruction",
    [
        "null_identity",
        "custom_columns",
        "custom_indexes",
        "custom_dependencies",
        "referenced_identity",
        "replacement_collision",
    ],
)
def test_unknown_or_invalid_retained_truth_refuses_without_data_loss(database, metadata, obstruction):
    extra = ", source_evidence TEXT" if obstruction == "custom_columns" else ""
    with database.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE retained (id VARCHAR(36) PRIMARY KEY, attempts INTEGER NOT NULL{extra})"
        )
        identity = "NULL" if obstruction == "null_identity" else "'retained-identity'"
        connection.exec_driver_sql(f"INSERT INTO retained (id, attempts) VALUES ({identity}, 3)")
        if obstruction == "custom_indexes":
            connection.exec_driver_sql("CREATE INDEX custom_evidence_index ON retained (attempts)")
        elif obstruction == "custom_dependencies":
            connection.exec_driver_sql(
                "CREATE TRIGGER custom_guard BEFORE DELETE ON retained BEGIN SELECT RAISE(ABORT, 'preserve'); END"
            )
        elif obstruction == "referenced_identity":
            connection.exec_driver_sql("CREATE TABLE linked (id VARCHAR(36) REFERENCES retained(id))")
        elif obstruction == "replacement_collision":
            connection.exec_driver_sql("CREATE TABLE _lotus_identity_upgrade_retained (evidence TEXT)")
        catalog = connection.exec_driver_sql("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").all()
        rows = connection.exec_driver_sql("SELECT * FROM retained").all()
    with pytest.raises(DurableSchemaMigrationRequiredError) as error:
        _upgrade(database, metadata)
    assert f"sqlite_identity_upgrade:retained.{obstruction}" in error.value.issues
    with database.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").all() == catalog
        )
        assert connection.exec_driver_sql("SELECT * FROM retained").all() == rows


def test_failure_after_replacement_rolls_back_original_data_and_catalog(database, metadata):
    with database.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE retained (id VARCHAR(36) PRIMARY KEY, attempts INTEGER NOT NULL)")
        connection.exec_driver_sql("INSERT INTO retained VALUES ('retained-identity', 3)")

    def fail(_connection):
        raise RuntimeError("induced owner failure")

    with pytest.raises(RuntimeError, match="induced owner failure"):
        create_durable_schema(
            database,
            metadata,
            schema_preflights=(lambda connection: upgrade_sqlite_primary_key_nullability(connection, metadata),),
            schema_upgrades=(fail,),
        )
    assert inspect(database).get_columns("retained")[0]["nullable"]
    with database.connect() as connection:
        assert connection.exec_driver_sql("SELECT * FROM retained").one() == ("retained-identity", 3)
        assert "_lotus_identity_upgrade_retained" not in inspect(connection).get_table_names()
