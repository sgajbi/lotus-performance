from __future__ import annotations

from typing import Protocol


class OperatorActionActorIdentity(Protocol):
    @property
    def operator_id(self) -> str: ...

    @property
    def tenant_id(self) -> str | None: ...


class OperatorActionCorrelationIdentity(OperatorActionActorIdentity, Protocol):
    @property
    def correlation_id(self) -> str | None: ...


def operator_action_actor_matches(
    entry: OperatorActionActorIdentity,
    *,
    operator_id: str,
    tenant_id: str | None,
) -> bool:
    return _normalize_required_identity(entry.operator_id) == _normalize_required_identity(
        operator_id
    ) and _normalize_optional_identity(entry.tenant_id) == _normalize_optional_identity(tenant_id)


def operator_action_correlation_matches(
    entry: OperatorActionCorrelationIdentity,
    *,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str,
) -> bool:
    return operator_action_actor_matches(
        entry, operator_id=operator_id, tenant_id=tenant_id
    ) and _normalize_optional_identity(entry.correlation_id) == _normalize_required_identity(correlation_id)


def operator_action_required_identity_matches(entry_value: str, candidate_value: str) -> bool:
    return _normalize_required_identity(entry_value) == _normalize_required_identity(candidate_value)


def operator_action_optional_identity_matches(entry_value: str | None, candidate_value: str | None) -> bool:
    return _normalize_optional_identity(entry_value) == _normalize_optional_identity(candidate_value)


def _normalize_required_identity(value: str) -> str:
    return value.strip()


def _normalize_optional_identity(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
