import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError

from app.adapters.composite_external_fact_schema import upgrade_external_fact_columns
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError


@pytest.mark.parametrize("partial", [False, True])
def test_upgrade_retains_populated_internal_facts_fk_index_and_repeats(partial):
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table("composite_definitions", metadata, Column("id", Integer, primary_key=True))
    table = Table(
        "composite_member_return_facts",
        metadata,
        Column("fact_key", Integer, primary_key=True),
        Column("composite_id", Integer, ForeignKey("composite_definitions.id")),
        Column("ending_market_value", Text, nullable=partial),
        Column("calculation_id", String(64), nullable=partial),
    )
    if partial:
        table.append_column(Column("source_authority_identity_json", Text))
    Index("ix_test_fact_owner", table.c.composite_id)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            metadata.create_all(connection)
            connection.execute(text("INSERT INTO composite_definitions VALUES (1)"))
            connection.execute(
                text(
                    "INSERT INTO composite_member_return_facts "
                    "(fact_key,composite_id,ending_market_value,calculation_id) VALUES (1,1,'160.00','genuine-calculation')"
                )
            )
            upgrade_external_fact_columns(connection, table)
            upgrade_external_fact_columns(connection, table)
            row = connection.execute(
                text(
                    "SELECT ending_market_value,calculation_id,source_authority_identity_json "
                    "FROM composite_member_return_facts"
                )
            ).one()
            assert tuple(row) == ("160.00", "genuine-calculation", None)
            inspector = inspect(connection)
            assert inspector.get_foreign_keys(table.name)[0]["referred_table"] == "composite_definitions"
            assert {i["name"] for i in inspector.get_indexes(table.name)} == {"ix_test_fact_owner"}
            assert "ck_composite_fact_internal_evidence" in {
                i["name"] for i in inspector.get_check_constraints(table.name)
            }
            with pytest.raises(IntegrityError):
                connection.execute(text("UPDATE composite_member_return_facts SET calculation_id=NULL"))
            with pytest.raises(IntegrityError):
                connection.execute(text("UPDATE composite_member_return_facts SET composite_id=999"))
    finally:
        engine.dispose()


def test_same_named_weakened_guard_refuses_without_mutation():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table(
        "composite_member_return_facts",
        metadata,
        Column("fact_key", Integer, primary_key=True),
        Column("ending_market_value", Text),
        Column("calculation_id", String(64)),
        Column("source_authority_identity_json", Text),
        CheckConstraint("1=1", name="ck_composite_fact_internal_evidence"),
    )
    try:
        with engine.begin() as connection:
            metadata.create_all(connection)
            with pytest.raises(DurableSchemaMigrationRequiredError, match="weakened_internal_guard"):
                upgrade_external_fact_columns(connection, table)
            assert inspect(connection).get_check_constraints(table.name)[0]["sqltext"] == "1=1"
    finally:
        engine.dispose()


def test_invalid_populated_partial_upgrade_rolls_back_schema_and_rows():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table(
        "composite_member_return_facts",
        metadata,
        Column("fact_key", Integer, primary_key=True),
        Column("ending_market_value", Text),
        Column("calculation_id", String(64)),
    )
    try:
        with engine.begin() as connection:
            metadata.create_all(connection)
            connection.execute(table.insert().values(fact_key=1, ending_market_value=None, calculation_id=None))
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                upgrade_external_fact_columns(connection, table)
        with engine.connect() as connection:
            assert "source_authority_identity_json" not in {
                c["name"] for c in inspect(connection).get_columns(table.name)
            }
            assert "_lotus_external_fact_upgrade" not in inspect(connection).get_table_names()
            assert connection.execute(table.select()).one().fact_key == 1
    finally:
        engine.dispose()
