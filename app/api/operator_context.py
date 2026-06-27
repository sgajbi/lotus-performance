from __future__ import annotations

from fastapi import HTTPException, Request

from app.services.operator_request_context import OperatorRequestContext


def _trimmed_request_header(request: Request, header_name: str) -> str:
    return request.headers.get(header_name, "").strip()


def _optional_trimmed_request_header(request: Request, header_name: str) -> str | None:
    return _trimmed_request_header(request, header_name) or None


def _operator_identity_from_headers(request: Request) -> str:
    actor_id = _trimmed_request_header(request, "X-Actor-Id")
    service_identity = _trimmed_request_header(request, "X-Service-Identity")
    return actor_id or service_identity


def resolve_operator_request_context(request: Request) -> OperatorRequestContext:
    operator_id = _operator_identity_from_headers(request)
    if not operator_id:
        raise HTTPException(status_code=400, detail="missing_operator_identity")

    tenant_id = _optional_trimmed_request_header(request, "X-Tenant-Id")
    correlation_id = _optional_trimmed_request_header(request, "X-Correlation-Id")
    return OperatorRequestContext(
        operator_id=operator_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
    )
