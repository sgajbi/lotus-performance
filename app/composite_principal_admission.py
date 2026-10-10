"""Outer verified admission for candidate routes and protected Composite metrics."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.adapters.composite_principal_credentials import (
    CredentialTrust,
    PrincipalAuthority,
    PrincipalDenial,
    VerifiedCompositePrincipal,
    resolve_composite_principal,
)
from app.enterprise_capability_rules import _CAPABILITY_OPERATIONS_RUNTIME_MANAGE, _CAPABILITY_OPERATIONS_RUNTIME_READ
from app.enterprise_payload_limits import (
    PayloadTooLargeError,
    _payload_too_large_response,
    _write_payload_limited_receive,
    _write_payload_too_large,
)
from app.enterprise_runtime_config import _max_write_payload_bytes
from app.observability import tenant_id_var

RESULT_CANDIDATE_PATH = "/performance/composites/result-candidates"
PRINCIPAL_STATE_KEY = "verified_composite_principal"
VERIFIED_SURFACE_STATE_KEY = "verified_composite_surface"
COMPOSITE_ANALYTICS_PATH = "/performance/composites/analytics"
COMPOSITE_RESULTS_PATH = COMPOSITE_ANALYTICS_PATH + "/results/"
RESULT_AUTHORITY_PATH = "/performance/composites/result-authorities"


def is_candidate_path(path):
    return path == RESULT_CANDIDATE_PATH or path.startswith(RESULT_CANDIDATE_PATH + "/")


def is_authority_path(path):
    return path == RESULT_AUTHORITY_PATH or path.startswith(RESULT_AUTHORITY_PATH + "/")


def _is_composite_result_route(scope):
    path = scope["path"]
    suffix = path.removeprefix(COMPOSITE_RESULTS_PATH)
    return (
        scope["method"] in ("GET", "HEAD")
        and path.startswith(COMPOSITE_RESULTS_PATH)
        and bool(suffix)
        and "/" not in suffix
    )


def verified_composite_surface(request: Request) -> str | None:
    if is_authority_path(getattr(getattr(request, "url", None), "path", "")):
        return "composite_result_authority"
    if is_candidate_path(getattr(getattr(request, "url", None), "path", "")):
        return "composite_result_candidates"
    # Only outer server middleware establishes this marker. Pending dispatch
    # fails closed in terminal logs if oversized bytes prevent classification.
    marker = getattr(request.state, VERIFIED_SURFACE_STATE_KEY, None)
    if marker == "composite_attribution":
        return marker
    if marker in ("composite_pooled_mwr", "composite_pooled_dispatch"):
        return "composite_pooled_mwr"
    return None


def _json_body_request(request: Request) -> bool:
    content_type = request.headers.get("content-type")
    if not content_type:
        return True
    message = Message()
    message["content-type"] = content_type
    return message.get_content_maintype() == "application" and (
        message.get_content_subtype() == "json" or message.get_content_subtype().endswith("+json")
    )


def _replay_body(receive: Receive, body: bytes, *, disconnected: bool) -> Receive:
    body_pending = True
    disconnect_pending = disconnected

    async def replay():
        nonlocal body_pending, disconnect_pending
        if body_pending:
            body_pending = False
            return {"type": "http.request", "body": body, "more_body": disconnected}
        if disconnect_pending:
            disconnect_pending = False
            return {"type": "http.disconnect"}
        return await receive()

    return replay


async def _composite_analytics_dispatch_body(request: Request, receive: Receive) -> tuple[str | None, Receive]:
    bound = _max_write_payload_bytes()
    if _write_payload_too_large(method=request.method, headers=request.headers, max_write_payload_bytes=bound):
        raise PayloadTooLargeError
    body, disconnected = await _bounded_dispatch_bytes(receive, bound)
    replay = _replay_body(receive, body, disconnected=disconnected)
    if disconnected:
        return None, replay
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return None, replay
    # Match Request.json()'s last-key-wins semantics and replay exact body bytes.
    return _protected_analytics_surface(payload), replay


def _protected_analytics_surface(payload):
    metric = payload.get("metric_id") if isinstance(payload, dict) else None
    if not isinstance(metric, str):
        return None
    surfaces = {
        "POOLED_MONEY_WEIGHTED_RETURN": "composite_pooled_mwr",
        "SINGLE_PERIOD_BRINSON_FACHLER": "composite_attribution",
    }
    return surfaces.get(metric)


async def _bounded_dispatch_bytes(receive: Receive, bound: int) -> tuple[bytes, bool]:
    limited_receive = _write_payload_limited_receive(receive, max_write_payload_bytes=bound)
    # Retain bounded bytes, not a potentially unbounded list of empty chunks.
    body = bytearray()
    disconnected = False
    while True:
        message = await limited_receive()
        if message["type"] == "http.disconnect":
            disconnected = True
            break
        if message["type"] == "http.request":
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
    return bytes(body), disconnected


async def _classify_surface(request: Request, receive: Receive):
    scope = request.scope
    candidate = is_candidate_path(scope["path"]) or is_authority_path(scope["path"])
    analytics_surface = "composite_pooled_mwr" if _is_composite_result_route(scope) else None
    if scope["method"] == "POST" and scope["path"] == COMPOSITE_ANALYTICS_PATH and _json_body_request(request):
        scope.setdefault("state", {})[VERIFIED_SURFACE_STATE_KEY] = "composite_pooled_dispatch"
        analytics_surface, receive = await _composite_analytics_dispatch_body(request, receive)
        scope["state"].pop(VERIFIED_SURFACE_STATE_KEY, None)
    return candidate, analytics_surface, receive


@dataclass(frozen=True)
class CompositePrincipalDeployment:
    trust: CredentialTrust | None = None
    authority: PrincipalAuthority | None = None


def get_composite_principal_deployment(application):
    # Only server startup/deployment can install trusted ports. No HTTP config.
    return getattr(application.state, "composite_principal_deployment", CompositePrincipalDeployment())


def trusted_request_principal(request: Request):
    principal = getattr(request.state, PRINCIPAL_STATE_KEY, None)
    return principal if isinstance(principal, VerifiedCompositePrincipal) else None


def _presented_credential(request):
    values = request.headers.getlist("authorization")
    if len(values) > 1:
        return PrincipalDenial("malformed_credential", True)
    if not values:
        return None
    scheme, separator, credential = values[0].partition(" ")
    if scheme.lower() != "bearer" or not separator or not credential or credential != credential.strip():
        return PrincipalDenial("malformed_credential", True)
    return credential


def _admitted_principal(request):
    credential = _presented_credential(request)
    if isinstance(credential, PrincipalDenial):
        return credential
    capability = (
        _CAPABILITY_OPERATIONS_RUNTIME_READ
        if request.method in ("GET", "HEAD")
        else _CAPABILITY_OPERATIONS_RUNTIME_MANAGE
    )
    deployment = get_composite_principal_deployment(request.app)
    return resolve_composite_principal(
        credential,
        trust=deployment.trust,
        authority=deployment.authority,
        now=datetime.now(UTC),
        required_capabilities=frozenset({capability}),
    )


def _denied_response(request, denial):
    from app.enterprise_readiness import emit_audit_event
    from app.services.error_details import safe_error_envelope

    status = 401 if denial.unauthenticated else 403
    emit_audit_event(
        action=f"DENY {request.method} {request.url.path}",
        actor_id="unresolved",
        tenant_id="unresolved",
        role="unresolved",
        correlation_id=request.headers.get("x-correlation-id"),
        metadata={"denial_class": denial.denial_class, "status_code": status},
    )
    return JSONResponse(
        status_code=status,
        content=safe_error_envelope(
            status_code=status,
            detail={
                "code": "PRINCIPAL_ADMISSION_DENIED",
                "message": "Principal admission refused.",
                "denial_class": denial.denial_class,
            },
            error_code="PRINCIPAL_ADMISSION_DENIED",
            retryable=False,
        ),
    )


class CompositePrincipalAdmissionMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        request = Request(scope)
        try:
            candidate, analytics_surface, receive = await _classify_surface(request, receive)
        except PayloadTooLargeError:
            return await _payload_too_large_response()(scope, receive, send)
        if not candidate and not analytics_surface:
            return await self.app(scope, receive, send)
        scope.setdefault("state", {})[VERIFIED_SURFACE_STATE_KEY] = _surface_name(
            scope["path"], candidate, analytics_surface
        )
        outcome = _admitted_principal(request)
        if isinstance(outcome, PrincipalDenial):
            response = _denied_response(request, outcome)
            return await response(scope, receive, send)
        scope.setdefault("state", {})[PRINCIPAL_STATE_KEY] = outcome
        token = tenant_id_var.set(outcome.tenant_id)
        try:
            await self.app(scope, receive, send)
        finally:
            tenant_id_var.reset(token)


def _surface_name(path, candidate, analytics_surface):
    if is_authority_path(path):
        return "composite_result_authority"
    return "composite_result_candidates" if candidate else analytics_surface
