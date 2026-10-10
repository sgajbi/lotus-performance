"""Real PostgreSQL parity using the existing isolated-schema/registered API flow."""

import pytest

from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url
from tests.integration import test_composite_attribution_api as contracts

attribution_runtime = contracts.attribution_runtime


@pytest.fixture
def attribution_database_url():
    return get_postgres_database_url()


def test_postgres_registered_or17_original(attribution_runtime):
    contracts.test_registered_or17_all_effect_cells_original_replay(attribution_runtime)


def test_postgres_registered_historical_corrections(attribution_runtime):
    contracts.test_registered_benchmark_classification_correction_preserves_both_originals(attribution_runtime)


def test_postgres_registered_fresh_process_original(attribution_runtime, attribution_database_url, tmp_path):
    contracts.test_registered_original_replays_in_fresh_process_without_source(
        attribution_runtime, attribution_database_url, tmp_path
    )


@pytest.mark.parametrize("stage", ["admission", "binding", "publication"])
def test_postgres_registered_current_selection_boundaries(attribution_runtime, monkeypatch, stage):
    contracts.test_registered_current_selection_rechecked_at_each_boundary(attribution_runtime, monkeypatch, stage)


@pytest.mark.parametrize("target", ["input", "result"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_postgres_original_custody(attribution_runtime, target, operation):
    contracts.test_registered_original_input_and_output_are_database_immutable(attribution_runtime, target, operation)


@pytest.mark.parametrize("denial", ["missing", "wrong-audience", "scope", "capability", "tenant"])
def test_postgres_verified_authorization(attribution_runtime, denial):
    contracts.test_registered_authorization_refuses_before_financial_reads(attribution_runtime, denial)


@pytest.mark.parametrize("evidence", ["absent", "twr-purpose"])
def test_postgres_independent_bf_purpose(attribution_runtime, evidence):
    contracts.test_registered_unavailable_or_wrong_financial_purpose_cannot_publish(attribution_runtime, evidence)


def test_postgres_strict_precision_before_source(attribution_runtime):
    contracts.test_registered_strict_precision_refuses_before_source_or_job(attribution_runtime)


def test_postgres_missing_guard_refuses_without_repair(attribution_runtime):
    contracts.test_registered_missing_input_guard_refuses_without_repair(attribution_runtime)


def test_postgres_corrected_member_original_identity(attribution_runtime, monkeypatch):
    contracts.test_registered_corrected_member_original_identity_never_aliases(attribution_runtime, monkeypatch)


def test_postgres_replay_without_recalculation_or_reapproval(attribution_runtime, monkeypatch):
    contracts.test_registered_replay_does_not_recalculate_or_reapprove(attribution_runtime, monkeypatch)


def test_postgres_purpose_rechecked_before_publication(attribution_runtime, monkeypatch):
    contracts.test_registered_financial_purpose_is_rechecked_before_publication(attribution_runtime, monkeypatch)


def test_postgres_two_populated_tenants(attribution_runtime, monkeypatch):
    contracts.test_registered_two_populated_tenants_keep_originals_separate(attribution_runtime, monkeypatch)


def test_postgres_conflicting_source_reference(attribution_runtime):
    contracts.test_registered_changed_source_reference_cannot_reuse_identity(attribution_runtime)


def test_postgres_withdrawal_preserves_original(attribution_runtime):
    contracts.test_registered_withdrawal_preserves_published_original_replay(attribution_runtime)


@pytest.mark.parametrize(
    "change", [{"worker_id": "stale-worker"}, {"tenant_id": "foreign"}, {"expected_attempt_count": 2}]
)
def test_postgres_binding_rejects_stale_or_foreign_lease(attribution_runtime, change):
    contracts.test_registered_input_binding_refuses_stale_or_foreign_lease(attribution_runtime, change)


def test_postgres_binding_transaction_rolls_back(attribution_runtime):
    contracts.test_registered_input_binding_rolls_back_interrupted_transaction(attribution_runtime)


def test_postgres_repeated_schema_apply_preserves_originals(attribution_runtime, attribution_database_url):
    contracts.test_registered_repeated_schema_apply_preserves_both_original_owners(
        attribution_runtime, attribution_database_url
    )


def test_postgres_retention_and_generic_writers_preserve_originals(attribution_runtime):
    contracts.test_registered_original_survives_ordinary_retention_and_generic_writers(attribution_runtime)


def test_postgres_verified_bf_audit(attribution_runtime, caplog):
    contracts.test_registered_bf_audit_names_metric_and_verified_actor(attribution_runtime, caplog)


@pytest.mark.parametrize("table", ["composite_attribution_inputs", "analytics_async_result"])
def test_postgres_truncate_cannot_remove_originals(attribution_runtime, table):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    client, _, _, _, headers, fixture, *_ = attribution_runtime
    path, original = contracts.run_request(attribution_runtime)
    with pytest.raises(IntegrityError, match="immutable"):
        with fixture.store._engine.begin() as connection:
            connection.execute(text(f"TRUNCATE TABLE {table}"))
    assert client.get(path, headers=headers).json() == original
