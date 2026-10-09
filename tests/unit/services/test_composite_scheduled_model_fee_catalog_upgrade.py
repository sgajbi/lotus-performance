"""Populated periodic catalog upgrade with real immutable custody and rollback."""

from copy import deepcopy

import pytest
from sqlalchemy import MetaData, event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateTable

from app.adapters.composite_model_fee_profile_records import CompositeModelFeeProfileModel
from app.adapters.composite_model_fee_profile_schema import model_fee_profile_guard_statements
from app.adapters.composite_model_fee_profile_upgrade import (
    _metadata_with_product_guard,
    upgrade_model_fee_profile_products,
)
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.models.composite_model_fees import CompositePeriodicModelFeeProfile
from app.models.composite_scheduled_model_fees import CompositeScheduledModelFeeProfile
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.durable_schema_creation import create_durable_schema
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_model_fee_helpers import profile_wire
from tests.composite_scheduled_model_fee_helpers import scheduled_profile_wire


@pytest.fixture
def legacy_catalog(tmp_path):
    url = "sqlite:///" + (tmp_path / "legacy-catalog.db").as_posix()
    evidence = apply_durable_schema(database_url=url)
    assert evidence.status == "passed", evidence
    store = CompositeMetadataStore(url)
    legacy = _metadata_with_product_guard(
        "product_name = 'CompositePeriodicModelFeeProfile' AND product_version = 'v1'", "sqlite"
    )
    with store._engine.begin() as connection:
        CompositeModelFeeProfileModel.__table__.drop(connection)
        connection.execute(CreateTable(legacy.tables["composite_model_fee_profiles"]))
        for statement in model_fee_profile_guard_statements(connection.dialect):
            connection.exec_driver_sql(statement)
    receipts = []
    for tenant in ("TENANT_A", "TENANT_B"):
        wire = deepcopy(profile_wire())
        wire["tenant_id"] = tenant
        receipts.append(
            store.publish_model_fee_profile(
                CompositePeriodicModelFeeProfile.model_validate(wire), tenant_id=tenant, actor_id="original-publisher"
            )
        )
    try:
        yield store, receipts
    finally:
        store.close()


def snapshot(store):
    with store._engine.connect() as connection:
        return (
            connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name").all(),
            connection.exec_driver_sql(
                "SELECT * FROM composite_model_fee_profiles ORDER BY tenant_id,profile_id,revision"
            ).all(),
        )


def test_owner_upgrade_preserves_json_digest_publisher_tenants_and_repeats(legacy_catalog):
    store, receipts = legacy_catalog
    original = snapshot(store)[1]
    store.create_schema()
    store.create_schema()
    store.verify_schema()
    assert snapshot(store)[1] == original
    for tenant, receipt in zip(("TENANT_A", "TENANT_B"), receipts, strict=True):
        assert (
            store.get_model_fee_profile(
                tenant_id=tenant, profile_id=receipt.profile.profile_id, revision=receipt.profile.revision
            )
            == receipt
        )
    scheduled = CompositeScheduledModelFeeProfile.model_validate(scheduled_profile_wire())
    published = store.publish_model_fee_profile(scheduled, tenant_id="TENANT_A", actor_id="new-publisher")
    assert published.profile == scheduled
    assert store.publish_model_fee_profile(scheduled, tenant_id="TENANT_A", actor_id="retry") == published


def test_runtime_refuses_without_ddl_or_rows_changed(legacy_catalog):
    store, _ = legacy_catalog
    before = snapshot(store)
    with pytest.raises(DurableSchemaMigrationRequiredError):
        store.verify_schema()
    assert snapshot(store) == before


@pytest.mark.parametrize(
    "ddl",
    [
        "ALTER TABLE composite_model_fee_profiles ADD COLUMN custom_truth TEXT",
        "CREATE INDEX custom_index ON composite_model_fee_profiles(published_by)",
        "CREATE TRIGGER custom_trigger AFTER INSERT ON composite_model_fee_profiles BEGIN SELECT 1; END",
        "CREATE VIEW custom_view AS SELECT * FROM composite_model_fee_profiles",
        "CREATE VIEW custom_view AS SELECT * FROM COMPOSITE_MODEL_FEE_PROFILES",
        'CREATE VIEW custom_view AS SELECT * FROM "Composite_Model_Fee_Profiles"',
        "CREATE TABLE _lotus_model_fee_catalog_upgrade (custom_truth TEXT)",
        "CREATE TABLE child (tenant TEXT,profile TEXT,revision TEXT,FOREIGN KEY(tenant,profile,revision) REFERENCES composite_model_fee_profiles(tenant_id,profile_id,revision))",
        "DROP TRIGGER trg_model_fee_profiles_immutable_update",
    ],
)
def test_unknown_schema_or_missing_guards_refuses_before_mutation(legacy_catalog, ddl):
    store, _ = legacy_catalog
    with store._engine.begin() as connection:
        connection.exec_driver_sql(ddl)
    before = snapshot(store)
    statements = []

    def record_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(store._engine, "before_cursor_execute", record_statement)
    try:
        with pytest.raises(DurableSchemaMigrationRequiredError):
            store.create_schema()
    finally:
        event.remove(store._engine, "before_cursor_execute", record_statement)
    assert not set(statements) & {"CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE", "REPLACE"}
    assert snapshot(store) == before


def test_later_owner_failure_rolls_back_catalog_and_guards(legacy_catalog):
    store, _ = legacy_catalog
    before = snapshot(store)

    def fail(connection):
        raise RuntimeError("controlled late failure")

    with pytest.raises(RuntimeError, match="controlled late failure"):
        create_durable_schema(
            store._engine, MetaData(), schema_preflights=(upgrade_model_fee_profile_products,), schema_upgrades=(fail,)
        )
    assert snapshot(store) == before


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE composite_model_fee_profiles SET published_by='replacement'",
        "DELETE FROM composite_model_fee_profiles",
    ],
)
def test_upgraded_guards_still_reject_mutation(legacy_catalog, sql):
    store, _ = legacy_catalog
    store.create_schema()
    before = snapshot(store)
    with pytest.raises(DBAPIError, match="immutable"):
        with store._engine.begin() as connection:
            connection.exec_driver_sql(sql)
    assert snapshot(store) == before
