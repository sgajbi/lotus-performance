from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorRequestContext:
    """Transport-neutral operator identity resolved for governed operator actions."""

    operator_id: str
    tenant_id: str | None
    correlation_id: str | None
