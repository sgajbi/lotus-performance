"""PostgreSQL prior scheduled-catalog migration and component publication custody."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import MetaData

from app.adapters.composite_model_fee_profile_schema import require_model_fee_profile_schema
from app.adapters.composite_model_fee_profile_upgrade import upgrade_model_fee_profile_products
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.models.composite_component_model_fees import CompositeComponentModelFeeProfile
from app.models.composite_scheduled_model_fees import CompositeScheduledModelFeeProfile
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.durable_schema_creation import create_durable_schema
from core.errors import APIConflictError
from scripts.durable_schema_apply import apply_durable_schema
from tests.benchmarks import test_postgres_composite_scheduled_model_fee as scheduled
from tests.composite_scheduled_model_fee_helpers import scheduled_profile_wire
from tests.unit.models.test_composite_component_model_fees import component_case

populated_model_fee_postgres = scheduled.populated_model_fee_postgres
legacy_catalog_postgres = scheduled.legacy_catalog_postgres


@pytest.fixture
def prior_scheduled_catalog(legacy_catalog_postgres):
    store, periodic_receipt = legacy_catalog_postgres
    with store._engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE composite_model_fee_profiles DROP CONSTRAINT ck_model_fee_profile_product"
        )
        connection.exec_driver_sql(
            "ALTER TABLE composite_model_fee_profiles ADD CONSTRAINT ck_model_fee_profile_product CHECK (product_name IN ('CompositePeriodicModelFeeProfile', 'CompositeScheduledModelFeeProfile') AND product_version = 'v1')"
        )
    scheduled_receipt = store.publish_model_fee_profile(
        CompositeScheduledModelFeeProfile.model_validate(scheduled_profile_wire()),
        tenant_id="TENANT_A",
        actor_id="original-scheduled-publisher",
    )
    return store, (periodic_receipt, scheduled_receipt)


def test_postgres_component_upgrade_preserves_both_original_products(prior_scheduled_catalog):
    store, receipts = prior_scheduled_catalog
    before = scheduled.snapshot(store)
    with pytest.raises(DurableSchemaMigrationRequiredError):
        store.verify_schema()
    assert scheduled.snapshot(store) == before
    store.create_schema()
    store.create_schema()
    store.verify_schema()
    after = scheduled.snapshot(store)
    assert after["rows"] == before["rows"]
    assert after["triggers"] == before["triggers"]
    for receipt in receipts:
        assert (
            store.get_model_fee_profile(
                tenant_id=receipt.profile.tenant_id,
                profile_id=receipt.profile.profile_id,
                revision=receipt.profile.revision,
            )
            == receipt
        )
    profile = CompositeComponentModelFeeProfile.model_validate(component_case()[0])
    published = store.publish_model_fee_profile(profile, tenant_id=profile.tenant_id, actor_id="component-publisher")
    assert published.profile == profile
    assert store.publish_model_fee_profile(profile, tenant_id=profile.tenant_id, actor_id="retry") == published


def test_postgres_component_upgrade_late_failure_rolls_back(prior_scheduled_catalog):
    store, _ = prior_scheduled_catalog
    before = scheduled.snapshot(store)

    def fail(connection):
        require_model_fee_profile_schema(connection)
        raise RuntimeError("controlled component upgrade failure")

    with pytest.raises(RuntimeError, match="controlled component upgrade failure"):
        create_durable_schema(
            store._engine, MetaData(), schema_preflights=(upgrade_model_fee_profile_products,), schema_upgrades=(fail,)
        )
    assert scheduled.snapshot(store) == before


@pytest.mark.parametrize(
    "ddl",
    [
        "ALTER TABLE composite_model_fee_profiles ADD COLUMN custom_truth TEXT",
        "ALTER TABLE composite_model_fee_profiles DISABLE TRIGGER trg_model_fee_profiles_immutable_update",
        "CREATE INDEX custom_component_catalog_index ON composite_model_fee_profiles(published_by)",
    ],
)
def test_postgres_component_upgrade_unknown_shape_refuses_without_mutation(prior_scheduled_catalog, ddl):
    store, _ = prior_scheduled_catalog
    with store._engine.begin() as connection:
        connection.exec_driver_sql(ddl)
    before = scheduled.snapshot(store)
    with pytest.raises(DurableSchemaMigrationRequiredError):
        store.create_schema()
    assert scheduled.snapshot(store) == before


def test_postgres_component_catalog_concurrent_retry_and_conflict(populated_model_fee_postgres):
    _, url = populated_model_fee_postgres
    assert apply_durable_schema(database_url=url).status == "passed"
    profile = CompositeComponentModelFeeProfile.model_validate(component_case()[0])
    store = CompositeMetadataStore(url)
    barrier = Barrier(2)

    def publish(actor):
        barrier.wait(timeout=10)
        return store.publish_model_fee_profile(profile, tenant_id=profile.tenant_id, actor_id=actor)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(publish, actor) for actor in ("publisher.a", "publisher.b")]
            receipts = [future.result(timeout=30) for future in futures]
        assert receipts[0] == receipts[1]
        assert receipts[0].profile == profile
        changed = profile.model_copy(update={"bundled_fee_context": "BUNDLED"})
        with pytest.raises(APIConflictError):
            store.publish_model_fee_profile(changed, tenant_id=profile.tenant_id, actor_id="replacement")
        assert (
            store.get_model_fee_profile(
                tenant_id=profile.tenant_id, profile_id=profile.profile_id, revision=profile.revision
            )
            == receipts[0]
        )
    finally:
        store.close()
