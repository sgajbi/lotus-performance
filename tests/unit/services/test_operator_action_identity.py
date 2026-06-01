from dataclasses import dataclass

from app.services.operator_action_identity import (
    operator_action_actor_matches,
    operator_action_correlation_matches,
    operator_action_required_identity_matches,
)


@dataclass(frozen=True)
class _IdentityEntry:
    operator_id: str
    tenant_id: str | None
    correlation_id: str | None


def test_operator_action_actor_matches_operator_and_tenant():
    entry = _IdentityEntry(operator_id="ops-user", tenant_id="tenant-a", correlation_id="corr-1")

    assert operator_action_actor_matches(entry, operator_id="ops-user", tenant_id="tenant-a")
    assert not operator_action_actor_matches(entry, operator_id="other-ops-user", tenant_id="tenant-a")
    assert not operator_action_actor_matches(entry, operator_id="ops-user", tenant_id="tenant-b")


def test_operator_action_actor_matches_canonicalized_identities():
    entry = _IdentityEntry(operator_id="ops-user", tenant_id=None, correlation_id="corr-1")

    assert operator_action_actor_matches(entry, operator_id=" ops-user ", tenant_id=" ")
    assert not operator_action_actor_matches(entry, operator_id=" ", tenant_id=None)


def test_operator_action_correlation_matches_operator_tenant_and_correlation():
    entry = _IdentityEntry(operator_id="ops-user", tenant_id="tenant-a", correlation_id="corr-1")

    assert operator_action_correlation_matches(
        entry,
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-1",
    )
    assert not operator_action_correlation_matches(
        entry,
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-2",
    )


def test_operator_action_correlation_matches_canonicalized_identities():
    entry = _IdentityEntry(operator_id="ops-user", tenant_id="tenant-a", correlation_id="corr-1")

    assert operator_action_correlation_matches(
        entry,
        operator_id=" ops-user ",
        tenant_id=" tenant-a ",
        correlation_id=" corr-1 ",
    )
    assert not operator_action_correlation_matches(
        entry,
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id=" ",
    )


def test_operator_action_required_identity_matches_canonicalized_values():
    assert operator_action_required_identity_matches("backup-123", " backup-123 ")
    assert not operator_action_required_identity_matches("backup-123", " ")
