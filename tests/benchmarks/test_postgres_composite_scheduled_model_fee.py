"""Actual PostgreSQL known-catalog upgrade and scheduled registered worker proof."""

import pytest
from sqlalchemy import MetaData, inspect
from sqlalchemy.exc import DBAPIError

from app.adapters.composite_model_fee_profile_schema import require_model_fee_profile_schema
from app.adapters.composite_model_fee_profile_upgrade import upgrade_model_fee_profile_products
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.core.config import get_settings
from app.models.composite_model_fees import CompositePeriodicModelFeeProfile
from app.models.composite_scheduled_model_fees import CompositeScheduledModelFeeProfile
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.durable_schema_creation import create_durable_schema
from scripts.durable_schema_apply import apply_durable_schema
from tests.benchmarks import test_postgres_composite_model_fee as periodic_controls
from tests.composite_model_fee_helpers import profile_wire
from tests.composite_scheduled_model_fee_helpers import scheduled_profile_wire

# Reuse the existing owned schema/runtime fixture, including its exact cleanup fence.
populated_model_fee_postgres = periodic_controls.populated_model_fee_postgres


@pytest.fixture
def legacy_catalog_postgres(populated_model_fee_postgres):
    _, url = populated_model_fee_postgres
    evidence = apply_durable_schema(database_url=url)
    assert evidence.status == "passed", evidence
    store = CompositeMetadataStore(url)
    with store._engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE composite_model_fee_profiles DROP CONSTRAINT ck_model_fee_profile_product"
        )
        connection.exec_driver_sql(
            "ALTER TABLE composite_model_fee_profiles ADD CONSTRAINT ck_model_fee_profile_product CHECK (product_name = 'CompositePeriodicModelFeeProfile' AND product_version = 'v1')"
        )
    receipt = store.publish_model_fee_profile(
        CompositePeriodicModelFeeProfile.model_validate(profile_wire()),
        tenant_id="TENANT_A",
        actor_id="original-publisher",
    )
    try:
        yield store, receipt
    finally:
        store.close()


def snapshot(store):
    with store._engine.connect() as connection:
        return {
            "rows": connection.exec_driver_sql(
                "SELECT * FROM composite_model_fee_profiles ORDER BY tenant_id,profile_id,revision"
            ).all(),
            "checks": inspect(connection).get_check_constraints("composite_model_fee_profiles"),
            "triggers": connection.exec_driver_sql(
                "SELECT t.tgname,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname='composite_model_fee_profiles' AND NOT t.tgisinternal ORDER BY t.tgname"
            ).all(),
        }


def test_postgres_populated_scheduled_catalog_upgrade_custody_and_runtime_refusal(legacy_catalog_postgres):
    store, receipt = legacy_catalog_postgres
    before = snapshot(store)
    with pytest.raises(DurableSchemaMigrationRequiredError):
        store.verify_schema()
    assert snapshot(store) == before
    store.create_schema()
    store.create_schema()
    store.verify_schema()
    assert snapshot(store)["rows"] == before["rows"]
    assert snapshot(store)["triggers"] == before["triggers"]
    assert (
        store.get_model_fee_profile(
            tenant_id="TENANT_A", profile_id=receipt.profile.profile_id, revision=receipt.profile.revision
        )
        == receipt
    )
    scheduled = CompositeScheduledModelFeeProfile.model_validate(scheduled_profile_wire())
    published = store.publish_model_fee_profile(scheduled, tenant_id="TENANT_A", actor_id="scheduled-publisher")
    assert published.profile == scheduled
    assert store.publish_model_fee_profile(scheduled, tenant_id="TENANT_A", actor_id="retry") == published
    for operation in (
        "UPDATE composite_model_fee_profiles SET published_by='replacement'",
        "DELETE FROM composite_model_fee_profiles",
        "TRUNCATE composite_model_fee_profiles",
    ):
        with pytest.raises(DBAPIError, match="immutable"), store._engine.begin() as connection:
            connection.exec_driver_sql(operation)
    assert (
        store.get_model_fee_profile(tenant_id="TENANT_B", profile_id=scheduled.profile_id, revision=scheduled.revision)
        is None
    )


def test_postgres_late_failure_rolls_back_catalog_expansion(legacy_catalog_postgres):
    store, _ = legacy_catalog_postgres
    before = snapshot(store)

    def fail(connection):
        require_model_fee_profile_schema(connection)
        raise RuntimeError("controlled late failure")

    with pytest.raises(RuntimeError, match="controlled late failure"):
        create_durable_schema(
            store._engine, MetaData(), schema_preflights=(upgrade_model_fee_profile_products,), schema_upgrades=(fail,)
        )
    assert snapshot(store) == before


@pytest.mark.parametrize(
    "ddl",
    [
        "ALTER TABLE composite_model_fee_profiles ADD COLUMN custom_truth TEXT",
        "ALTER TABLE composite_model_fee_profiles DISABLE TRIGGER trg_model_fee_profiles_immutable_update",
        "CREATE INDEX custom_catalog_index ON composite_model_fee_profiles(published_by)",
    ],
)
def test_postgres_unknown_catalog_shape_refuses_unchanged(legacy_catalog_postgres, ddl):
    store, _ = legacy_catalog_postgres
    with store._engine.begin() as connection:
        connection.exec_driver_sql(ddl)
    before = snapshot(store)
    with pytest.raises(DurableSchemaMigrationRequiredError):
        store.create_schema()
    assert snapshot(store) == before


def test_postgres_scheduled_registered_worker_reopen_and_pinned_replay(populated_model_fee_postgres, monkeypatch):
    from tests.integration.test_composite_scheduled_model_fee_materialization_api import (
        test_scheduled_registered_worker_preserves_original_economics_and_profile as registered_control,
    )

    _, url = populated_model_fee_postgres
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    registered_control(monkeypatch, url)


def test_postgres_scheduled_fresh_process_replay_without_latest_or_child_lookup(
    populated_model_fee_postgres, monkeypatch, tmp_path
):
    from tests.benchmarks.composite_model_fee_process_controls import assert_fresh_model_fee_replay
    from tests.integration.test_composite_scheduled_model_fee_materialization_api import (
        test_scheduled_registered_worker_preserves_original_economics_and_profile as registered_control,
    )

    _, url = populated_model_fee_postgres
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    captured = {}

    def capture(packet, wire, command, retained, periods):
        captured.update(
            database_url=url,
            packet=packet,
            wire=wire,
            command=command.model_dump(mode="json"),
            retained=retained,
            periods=periods,
        )

    registered_control(monkeypatch, url, capture=capture)
    assert_fresh_model_fee_replay(captured, tmp_path)


@pytest.mark.parametrize("changed_binding", [False, True])
def test_postgres_scheduled_multiwindow_method_and_financial_history(
    populated_model_fee_postgres, monkeypatch, changed_binding
):
    from tests.integration.test_composite_scheduled_model_fee_history_api import (
        test_registered_scheduled_history_unequal_rates_and_full_binding as registered_history,
    )

    _, url = populated_model_fee_postgres
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    registered_history(monkeypatch, url, changed_binding)
