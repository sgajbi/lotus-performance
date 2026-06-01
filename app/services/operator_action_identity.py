from __future__ import annotations

from typing import Protocol

from app.services.operator_action_evidence_strings import (
    normalize_optional_evidence_identifier,
    normalize_required_evidence_identifier,
)


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
    return _required_identity_matches(entry.operator_id, operator_id) and _optional_identity_matches(
        entry.tenant_id, tenant_id
    )


def operator_action_correlation_matches(
    entry: OperatorActionCorrelationIdentity,
    *,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str,
) -> bool:
    return operator_action_actor_matches(
        entry, operator_id=operator_id, tenant_id=tenant_id
    ) and _required_identity_matches(entry.correlation_id or "", correlation_id)


def operator_action_required_identity_matches(entry_value: str, candidate_value: str) -> bool:
    return _required_identity_matches(entry_value, candidate_value)


def operator_action_optional_identity_matches(entry_value: str | None, candidate_value: str | None) -> bool:
    return _optional_identity_matches(entry_value, candidate_value)


def _required_identity_matches(entry_value: str, candidate_value: str) -> bool:
    try:
        return normalize_required_evidence_identifier(
            entry_value,
            field_name="operator_action_identity",
        ) == normalize_required_evidence_identifier(
            candidate_value,
            field_name="operator_action_identity",
        )
    except ValueError:
        return False


def _optional_identity_matches(entry_value: str | None, candidate_value: str | None) -> bool:
    try:
        return normalize_optional_evidence_identifier(entry_value) == normalize_optional_evidence_identifier(
            candidate_value
        )
    except ValueError:
        return False
