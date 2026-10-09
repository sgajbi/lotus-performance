"""Outer verified admission for the bounded result-candidate route family."""

from dataclasses import dataclass
from datetime import UTC, datetime

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
from app.observability import tenant_id_var

RESULT_CANDIDATE_PATH = "/performance/composites/result-candidates"
PRINCIPAL_STATE_KEY = "verified_composite_principal"


def is_candidate_path(path):
    return path == RESULT_CANDIDATE_PATH or path.startswith(RESULT_CANDIDATE_PATH + "/")


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
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or not is_candidate_path(scope["path"]):
            return await self.app(scope, receive, send)
        request = Request(scope)
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
