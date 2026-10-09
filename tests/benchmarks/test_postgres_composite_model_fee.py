"""Real PostgreSQL owner migration proof in a newly owned isolated schema."""

import re

import pytest
from sqlalchemy import MetaData, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.adapters.composite_materialization_schema import require_materialization_schema
from app.adapters.composite_materialization_view_upgrade import upgrade_materialization_return_views
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.durable_schema_creation import create_durable_schema
from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url, owned_postgres_runtime_stores
from tests.composite_model_fee_schema_helpers import create_populated_legacy_ledger


@pytest.fixture
def populated_model_fee_postgres(monkeypatch):
    url = get_postgres_database_url()
    schema = re.fullmatch(r"-csearch_path=(lotus_perf_bench_[0-9a-f]{32})", make_url(url).query["options"])
    assert schema is not None, "Cleanup requires exact owned isolated-schema provenance"
    ledger = CompositeMaterializationStore(url)
    assert ledger._engine.dialect.name == "postgresql"
    try:
        create_populated_legacy_ledger(ledger._engine)
        with owned_postgres_runtime_stores(url, monkeypatch):
            yield ledger, url
    finally:
        # Delete only the fresh schema created by get_postgres_database_url;
        # the database and other callers' runtime schemas remain untouched.
        with ledger._engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema.group(1)}" CASCADE')
            assert not inspect(connection).has_schema(schema.group(1))
        ledger.close()


def retained_rows(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT * FROM composite_materializations ORDER BY return_view, restatement_sequence"
        ).all()


def test_postgres_catalog_custody_conflict_guards_and_loss_refusal(populated_model_fee_postgres):
    from scripts.durable_schema_apply import apply_durable_schema
    from tests.unit.services.test_composite_model_fee_profile_catalog import (
        test_database_mutation_guard_rejects_retained_content,
        test_original_custody_retry_correction_and_exact_binding,
        test_populated_rollback_refuses_and_empty_rollback_is_owner_only,
    )

    _, url = populated_model_fee_postgres
    evidence = apply_durable_schema(database_url=url)
    assert evidence.status == "passed", evidence
    store = CompositeMetadataStore(url)
    try:
        # Empty owner rollback first, then retain content permanently. Subsequent
        # controls use different profile identities in separately owned schemas.
        test_populated_rollback_refuses_and_empty_rollback_is_owner_only(store)
        test_original_custody_retry_correction_and_exact_binding(store)
        for operation in (
            "UPDATE composite_model_fee_profiles SET published_by='replacement'",
            "DELETE FROM composite_model_fee_profiles",
            "TRUNCATE composite_model_fee_profiles",
        ):
            test_database_mutation_guard_rejects_retained_content(store, operation)
    finally:
        store.close()


def test_postgres_concurrent_profile_identity_conflict(populated_model_fee_postgres):
    from scripts.durable_schema_apply import apply_durable_schema
    from tests.unit.services.test_composite_model_fee_profile_catalog import (
        test_concurrent_conflicting_identity_preserves_one_original,
    )

    _, url = populated_model_fee_postgres
    assert apply_durable_schema(database_url=url).status == "passed"
    store = CompositeMetadataStore(url)
    try:
        test_concurrent_conflicting_identity_preserves_one_original(store)
    finally:
        store.close()


@pytest.mark.parametrize("basis", ["GROSS", "NET"])
def test_postgres_registered_model_fee_worker_replay_and_actual_net_refusal(
    populated_model_fee_postgres, monkeypatch, basis
):
    from app.core.config import get_settings
    from scripts.durable_schema_apply import apply_durable_schema
    from tests.integration.test_composite_model_fee_materialization_api import (
        test_registered_model_fee_worker_retention_replay_and_actual_net_refusal as registered_control,
    )

    ledger, url = populated_model_fee_postgres
    assert ledger._engine.dialect.name == "postgresql"
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    registered_control(monkeypatch, url, basis)


def test_postgres_fresh_process_replays_original_profile_without_child_lookup(
    populated_model_fee_postgres, monkeypatch, tmp_path
):
    from app.core.config import get_settings
    from scripts.durable_schema_apply import apply_durable_schema
    from tests.integration.test_composite_model_fee_materialization_api import (
        test_registered_model_fee_worker_retention_replay_and_actual_net_refusal as registered_control,
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

    registered_control(monkeypatch, url, "GROSS", capture=capture)
    from tests.benchmarks.composite_model_fee_process_controls import assert_fresh_model_fee_replay

    assert_fresh_model_fee_replay(captured, tmp_path)


@pytest.mark.parametrize("owner", ["ledger", "shared"])
def test_postgres_populated_legacy_view_upgrade_preserves_rows_and_guards(populated_model_fee_postgres, owner):
    ledger, url = populated_model_fee_postgres
    before = retained_rows(ledger._engine)
    schema_owner = ledger if owner == "ledger" else CompositeMetadataStore(url)
    try:
        schema_owner.create_schema()
        schema_owner.create_schema()
        assert retained_rows(ledger._engine) == before
        assert len(before) == 8
        with ledger._engine.connect() as connection:
            require_materialization_schema(connection)
        with ledger._engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE composite_materializations SET return_view='NET_MODEL_FEE' WHERE return_view='GROSS'"
            )
        with pytest.raises(DBAPIError), ledger._engine.begin() as connection:
            connection.exec_driver_sql("UPDATE composite_materializations SET return_view='NET_UNSUPPORTED'")
    finally:
        if schema_owner is not ledger:
            schema_owner.close()


def test_postgres_later_owner_failure_rolls_back_guard_and_every_row(populated_model_fee_postgres):
    ledger, _ = populated_model_fee_postgres
    before = retained_rows(ledger._engine)
    with ledger._engine.connect() as connection:
        guards = inspect(connection).get_check_constraints("composite_materializations")

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
    assert retained_rows(ledger._engine) == before
    with ledger._engine.connect() as connection:
        assert inspect(connection).get_check_constraints("composite_materializations") == guards
