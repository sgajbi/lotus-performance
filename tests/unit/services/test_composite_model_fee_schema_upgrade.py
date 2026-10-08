"""Populated owner migration controls; no runtime or institutional qualification."""

from __future__ import annotations

import pytest
from sqlalchemy import MetaData, inspect
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateTable

from app.adapters.composite_materialization_records import CompositeMaterializationModel
from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.adapters.composite_materialization_schema import (
    CompositeMaterializationMigrationRequiredError,
    require_materialization_schema,
)
from app.adapters.composite_materialization_view_upgrade import upgrade_materialization_return_views
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.durable_schema_creation import create_durable_schema
from tests.composite_model_fee_schema_helpers import create_populated_legacy_ledger


@pytest.fixture
def legacy_ledger(tmp_path):
    url = "sqlite:///" + str(tmp_path / "legacy-model-fee.db").replace("\\", "/")
    store = CompositeMaterializationStore(url)
    create_populated_legacy_ledger(store._engine)
    try:
        yield store, url
    finally:
        store.close()


def snapshot(engine):
    with engine.connect() as connection:
        ddl = connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
        ).all()
        rows = connection.exec_driver_sql(
            "SELECT * FROM composite_materializations ORDER BY return_view, restatement_sequence"
        ).all()
        return ddl, rows


@pytest.mark.parametrize("owner", ["ledger", "shared"])
def test_owner_upgrade_preserves_all_legacy_views_states_and_repeats(legacy_ledger, owner):
    ledger, url = legacy_ledger
    before = snapshot(ledger._engine)[1]
    schema_owner = ledger if owner == "ledger" else CompositeMetadataStore(url)
    try:
        schema_owner.create_schema()
        schema_owner.create_schema()
        assert snapshot(ledger._engine)[1] == before
        assert len(before) == 8
        with ledger._engine.connect() as connection:
            require_materialization_schema(connection)
            assert "_lotus_model_fee_view_upgrade" not in inspect(connection).get_table_names()
    finally:
        if schema_owner is not ledger:
            schema_owner.close()


def test_runtime_verification_refuses_legacy_without_mutation(legacy_ledger):
    ledger, url = legacy_ledger
    before = snapshot(ledger._engine)
    runtime = CompositeMetadataStore(url)
    try:
        with pytest.raises(DurableSchemaMigrationRequiredError):
            runtime.verify_schema()
        assert snapshot(ledger._engine) == before
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "custom_ddl",
    [
        "ALTER TABLE composite_materializations ADD COLUMN custom_truth TEXT",
        "CREATE INDEX custom_index ON composite_materializations(actor_id)",
        "CREATE TRIGGER custom_trigger AFTER INSERT ON composite_materializations BEGIN SELECT 1; END",
        "CREATE VIEW custom_view AS SELECT * FROM composite_materializations",
        "CREATE TABLE _lotus_model_fee_view_upgrade (custom_truth TEXT)",
        "CREATE TABLE child (tenant TEXT, id TEXT, FOREIGN KEY(tenant,id) REFERENCES composite_materializations(tenant_id,materialization_id))",
    ],
)
def test_unknown_legacy_dependencies_refuse_without_mutation(legacy_ledger, custom_ddl):
    ledger, _ = legacy_ledger
    with ledger._engine.begin() as connection:
        connection.exec_driver_sql(custom_ddl)
    before = snapshot(ledger._engine)
    with pytest.raises(CompositeMaterializationMigrationRequiredError):
        ledger.create_schema()
    assert snapshot(ledger._engine) == before


def test_later_owner_failure_rolls_back_replacement_and_all_rows(legacy_ledger):
    ledger, _ = legacy_ledger
    before = snapshot(ledger._engine)

    def fail_after_upgrade(connection):
        require_materialization_schema(connection)
        raise RuntimeError("controlled subsequent owner failure")

    with pytest.raises(RuntimeError, match="controlled subsequent"):
        create_durable_schema(
            ledger._engine,
            MetaData(),
            schema_preflights=(upgrade_materialization_return_views,),
            schema_upgrades=(fail_after_upgrade,),
        )
    assert snapshot(ledger._engine) == before


def test_upgraded_database_accepts_model_view_and_rejects_unsupported_view(legacy_ledger):
    ledger, _ = legacy_ledger
    ledger.create_schema()
    # Database enum admission is separate from JSON/evidence admission, which
    # remains enforced when the repository decodes and claims a command.
    with ledger._engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE composite_materializations SET return_view='NET_MODEL_FEE' WHERE return_view='GROSS'"
        )
    with pytest.raises(DBAPIError):
        with ledger._engine.begin() as connection:
            connection.exec_driver_sql("UPDATE composite_materializations SET return_view='NET_UNSUPPORTED'")


@pytest.mark.parametrize("predicate", ["return_view <> ''", "return_view IN ('GROSS')"])
def test_unknown_view_guard_is_not_repaired(tmp_path, predicate):
    url = "sqlite:///" + str(tmp_path / "unknown-guard.db").replace("\\", "/")
    ledger = CompositeMaterializationStore(url)
    ddl = str(CreateTable(CompositeMaterializationModel.__table__).compile(dialect=ledger._engine.dialect))
    ddl = ddl.replace("return_view IN ('GROSS', 'NET_ACTUAL', 'NET_MODEL_FEE')", predicate)
    try:
        with ledger._engine.begin() as connection:
            connection.exec_driver_sql(ddl)
        before = snapshot(ledger._engine)
        with pytest.raises(CompositeMaterializationMigrationRequiredError):
            ledger.create_schema()
        assert snapshot(ledger._engine) == before
    finally:
        ledger.close()
