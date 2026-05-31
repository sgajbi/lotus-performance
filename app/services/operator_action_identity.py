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
    return entry.operator_id == operator_id and entry.tenant_id == tenant_id


def operator_action_correlation_matches(
    entry: OperatorActionCorrelationIdentity,
    *,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str,
) -> bool:
    return (
        operator_action_actor_matches(entry, operator_id=operator_id, tenant_id=tenant_id)
        and entry.correlation_id == correlation_id
    )
