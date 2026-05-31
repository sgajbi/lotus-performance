import pytest
from fastapi import HTTPException, Request

from app.api.operator_context import resolve_operator_request_context


def _request_with_headers(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "headers": headers})


def test_resolve_operator_request_context_prefers_actor_identity():
    request = _request_with_headers(
        [
            (b"x-actor-id", b"ops-user"),
            (b"x-service-identity", b"automation-user"),
            (b"x-tenant-id", b"tenant-a"),
            (b"x-correlation-id", b"corr-123"),
        ]
    )

    context = resolve_operator_request_context(request)

    assert context.operator_id == "ops-user"
    assert context.tenant_id == "tenant-a"
    assert context.correlation_id == "corr-123"


def test_resolve_operator_request_context_falls_back_to_service_identity():
    request = _request_with_headers([(b"x-service-identity", b"lotus-platform")])

    context = resolve_operator_request_context(request)

    assert context.operator_id == "lotus-platform"
    assert context.tenant_id is None
    assert context.correlation_id is None


def test_resolve_operator_request_context_rejects_missing_identity():
    request = _request_with_headers([])

    with pytest.raises(HTTPException) as exc_info:
        resolve_operator_request_context(request)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "missing_operator_identity"
