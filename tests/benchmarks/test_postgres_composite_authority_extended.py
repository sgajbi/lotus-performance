"""PostgreSQL parity of the owning extended authority acceptance suite."""

import pytest

from tests.benchmarks.postgres_runtime_helpers import get_postgres_database_url
from tests.composite_result_authority_helpers import AuthorityFixture
from tests.unit.services import test_composite_authority_extended_storage as acceptance


@pytest.fixture
def authority(monkeypatch):
    fixture = AuthorityFixture(get_postgres_database_url(), monkeypatch)
    try:
        yield fixture
    finally:
        fixture.close()


def test_postgres_monthly_correction_and_wider_original(authority):
    acceptance.test_monthly_correction_atomically_stales_wider_projection_preserving_original(authority)


def test_postgres_frozen_wider_dependency(authority):
    acceptance.test_frozen_wider_dependency_blocks_correction_until_exact_reopen_and_fresh_preview(authority)


def test_postgres_complete_bundle_protection(authority):
    acceptance.test_bundle_rejects_partial_protection_and_preserves_complete_membership(authority)


def test_postgres_two_populated_tenants(authority):
    acceptance.test_two_populated_tenants_keep_originals_and_all_read_selectors_isolated(authority)


def test_postgres_whole_owner_rollback(authority, monkeypatch):
    acceptance.test_failure_after_history_and_pointer_write_rolls_back_whole_owner_transaction(authority, monkeypatch)


def test_postgres_restarted_owners(authority):
    acceptance.test_independent_restarted_owners_replay_committed_original_after_approval_expiry(authority)


def test_postgres_populated_predecessor_migration(authority):
    acceptance.test_populated_predecessor_migration_retains_originals_and_is_repeatable(authority)


def test_postgres_missing_guard_refusal(authority):
    acceptance.test_read_only_schema_verification_refuses_missing_guard_without_repair(authority)


@pytest.mark.parametrize("boundary", ["decisions", "revisions", "scopes", "committed"])
def test_postgres_abrupt_owner_death(authority, tmp_path, boundary):
    acceptance.test_abrupt_process_death_at_actual_owner_boundaries(authority, tmp_path, boundary)
