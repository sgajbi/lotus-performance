from typing import Any, Awaitable, Callable, Protocol

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.enterprise_audit_events import _apply_enterprise_policy_header
from app.enterprise_authorization import (
    _allowed_audit_metadata,
    _authorization_denial_metadata,
    _authorize_enterprise_request,
    _denied_request_action,
    _request_action,
)
from app.enterprise_payload_limits import _payload_too_large_response, _write_payload_too_large
from app.enterprise_request_context import _audit_identity_from_headers
from app.enterprise_response_envelopes import _authorization_denied_response_envelope
from app.enterprise_runtime_config import _max_write_payload_bytes


class AuditEventEmitter(Protocol):
    def __call__(
        self,
        *,
        action: str,
        actor_id: str,
        tenant_id: str,
        role: str,
        correlation_id: str | None,
        metadata: dict[str, Any],
    ) -> None: ...


def _authorization_denied_response(
    *,
    method: str,
    path: str,
    reason: str | None,
    audit_identity: dict[str, str],
    emit_audit_event: AuditEventEmitter,
) -> JSONResponse:
    emit_audit_event(
        action=_denied_request_action(method=method, path=path),
        **audit_identity,
        metadata=_authorization_denial_metadata(reason),
    )
    return _authorization_denied_response_envelope(reason)


def _emit_allowed_audit_event(
    *,
    method: str,
    path: str,
    audit_identity: dict[str, str],
    metadata: dict[str, Any],
    emit_audit_event: AuditEventEmitter,
) -> None:
    emit_audit_event(
        action=_request_action(method=method, path=path),
        **audit_identity,
        metadata=metadata,
    )


def build_enterprise_audit_middleware(
    *,
    emit_audit_event: AuditEventEmitter,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    # Enforce enterprise audit and authorization policy on governed surfaces.
    async def middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if _write_payload_too_large(
            method=request.method,
            headers=request.headers,
            max_write_payload_bytes=_max_write_payload_bytes(),
        ):
            return _payload_too_large_response()

        audit_identity = _audit_identity_from_headers(request.headers)
        authorized, reason = _authorize_enterprise_request(
            method=request.method,
            path=request.url.path,
            headers=dict(request.headers),
        )
        if not authorized:
            return _authorization_denied_response(
                method=request.method,
                path=request.url.path,
                reason=reason,
                audit_identity=audit_identity,
                emit_audit_event=emit_audit_event,
            )

        response = await call_next(request)
        _apply_enterprise_policy_header(response)
        allowed_audit_metadata = _allowed_audit_metadata(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        if allowed_audit_metadata is not None:
            _emit_allowed_audit_event(
                method=request.method,
                path=request.url.path,
                audit_identity=audit_identity,
                metadata=allowed_audit_metadata,
                emit_audit_event=emit_audit_event,
            )
        return response

    return middleware
