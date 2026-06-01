from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class OperatorRequestContext:
    operator_id: str
    tenant_id: str | None
    correlation_id: str | None


def resolve_operator_request_context(request: Request) -> OperatorRequestContext:
    actor_id = request.headers.get("X-Actor-Id", "").strip()
    service_identity = request.headers.get("X-Service-Identity", "").strip()
    operator_id = actor_id or service_identity
    if not operator_id:
        raise HTTPException(status_code=400, detail="missing_operator_identity")

    tenant_id = request.headers.get("X-Tenant-Id", "").strip() or None
    correlation_id = request.headers.get("X-Correlation-Id", "").strip() or None
    return OperatorRequestContext(
        operator_id=operator_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
    )
