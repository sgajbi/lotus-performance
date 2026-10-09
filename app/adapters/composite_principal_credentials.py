"""Performance's Ed25519 consumer of Lotus principal-credential/resolution v1.

Trust inputs and current grants come from deployment-owned ports. JWT claims and
HTTP actor/role/tenant headers never supply grants. No issuer or grant store is
configured by default. Platform's automation module is not a runtime dependency.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, TypeGuard

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


@dataclass(frozen=True)
class PrincipalDenial:
    denial_class: str
    unauthenticated: bool


@dataclass(frozen=True)
class PrincipalGrants:
    capabilities: frozenset[str]
    portfolio_scope: frozenset[str]


@dataclass(frozen=True)
class VerifiedCompositePrincipal:
    principal_kind: str
    subject: str
    tenant_id: str
    capabilities: frozenset[str]
    portfolio_scope: frozenset[str]
    credential_id: str
    delegated_actor: str | None = None


class PrincipalAuthorityUnavailable(RuntimeError):
    """Trusted revocation, membership or grant evidence cannot be answered."""


class PrincipalAuthority(Protocol):
    def revoked(self, subject: str, credential_id: str) -> bool: ...
    def tenant_member(self, subject: str, tenant_id: str) -> bool: ...
    def grants(self, subject: str, tenant_id: str) -> PrincipalGrants: ...
    def application_grants(self, application: str, tenant_id: str) -> PrincipalGrants: ...


@dataclass(frozen=True)
class CredentialTrust:
    expected_issuer: str
    expected_audience: str
    jwks: Mapping[str, Any]


def _identifier(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value) and value == value.strip() and len(value) <= 128


def _decode(segment: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        raise ValueError("Noncanonical base64url")
    decoded = base64.b64decode(segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != segment:
        raise ValueError("Noncanonical base64url")
    return decoded


def _json_segment(segment: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate signed JSON key")
            result[key] = value
        return result

    payload = json.loads(_decode(segment), object_pairs_hook=pairs)
    if not isinstance(payload, dict):
        raise ValueError("Signed segment must be an object")
    return payload


def _supported_signing_key(key):
    return (
        (key.get("kty"), key.get("crv")) == ("OKP", "Ed25519")
        and key.get("alg") in (None, "EdDSA")
        and key.get("use") in (None, "sig")
    )


def _matching_keys(keys, kid):
    return [key for key in keys if isinstance(key, dict) and key.get("kid") == kid]


def _public_key(trust: CredentialTrust, kid: str) -> Ed25519PublicKey | None:
    keys = trust.jwks.get("keys")
    if not isinstance(keys, list):
        return None
    matches = _matching_keys(keys, kid)
    if len(matches) != 1 or not _supported_signing_key(matches[0]):
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(_decode(matches[0]["x"]))
    except (KeyError, TypeError, ValueError):
        return None


def _jws_key_id(header):
    if header.get("alg") != "EdDSA" or header.get("crit") or header.get("b64") is False:
        return PrincipalDenial("malformed_credential", True)
    kid = header.get("kid")
    return kid if isinstance(kid, str) and kid else PrincipalDenial("malformed_credential", True)


def _signed_claims(credential, trust):
    try:
        header_wire, payload_wire, signature_wire = credential.split(".")
        header, claims = _json_segment(header_wire), _json_segment(payload_wire)
        signature = _decode(signature_wire)
        signing_input = f"{header_wire}.{payload_wire}".encode("ascii")
    except (ValueError, TypeError, UnicodeError):
        return PrincipalDenial("malformed_credential", True)
    kid = _jws_key_id(header)
    if isinstance(kid, PrincipalDenial):
        return kid
    public_key = _public_key(trust, kid)
    if public_key is None:
        return PrincipalDenial("unknown_key_id", True)
    try:
        public_key.verify(signature, signing_input)
    except InvalidSignature:
        return PrincipalDenial("present_but_unverified", True)
    return claims


def _audience_allowed(value, expected):
    audiences = [value] if isinstance(value, str) else value
    if not isinstance(audiences, list):
        return False
    return all(isinstance(item, str) for item in audiences) and expected in audiences


def _not_before_valid(value, instant):
    return value is None or (type(value) is int and instant >= value)


def _claim_denial(claims, trust, now):
    if claims.get("iss") != trust.expected_issuer:
        return PrincipalDenial("wrong_issuer", True)
    if not _audience_allowed(claims.get("aud"), trust.expected_audience):
        return PrincipalDenial("wrong_audience", True)
    instant, expiry = int(now.timestamp()), claims.get("exp")
    if type(expiry) is not int or instant >= expiry:
        return PrincipalDenial("expired_credential", True)
    if not _not_before_valid(claims.get("nbf"), instant):
        return PrincipalDenial("expired_credential", True)
    return None


def verify_composite_credential(
    credential: str | None, *, trust: CredentialTrust, now: datetime
) -> PrincipalDenial | dict:
    if credential is None or not credential.strip():
        return PrincipalDenial("missing_credential", True)
    claims = _signed_claims(credential, trust)
    if isinstance(claims, PrincipalDenial):
        return claims
    return _claim_denial(claims, trust, now) or claims


@dataclass(frozen=True)
class _PrincipalIdentity:
    kind: str
    subject: str
    tenant: str
    credential_id: str
    actor: str | None


def _principal_identity(claims):
    subject, tenant, kind, credential_id = (claims.get(name) for name in ("sub", "tenant", "principal_kind", "jti"))
    if (
        not _identifier(subject)
        or not _identifier(tenant)
        or not _identifier(credential_id)
        or kind not in ("user", "service", "delegated")
    ):
        return PrincipalDenial("malformed_credential", True)
    actor = None
    if kind == "delegated":
        actor = claims.get("act")
        if not _identifier(actor):
            return PrincipalDenial("malformed_credential", True)
    return _PrincipalIdentity(kind, subject, tenant, credential_id, actor)


def _trusted_grants(identity, authority):
    if authority is None:
        return PrincipalDenial("grant_store_unavailable", False)
    try:
        if authority.revoked(identity.subject, identity.credential_id):
            return PrincipalDenial("revoked_principal", True)
        if not authority.tenant_member(identity.subject, identity.tenant):
            return PrincipalDenial("tenant_not_a_member", False)
        grants = authority.grants(identity.subject, identity.tenant)
        application = (
            authority.application_grants(identity.actor, identity.tenant) if identity.kind == "delegated" else None
        )
    except PrincipalAuthorityUnavailable:
        return PrincipalDenial("grant_store_unavailable", False)
    return grants, application


def _effective_grants(grants, application):
    if application is None:
        return grants
    return PrincipalGrants(
        grants.capabilities & application.capabilities, grants.portfolio_scope & application.portfolio_scope
    )


def _grant_denial(effective, application, required, requested):
    if not required <= effective.capabilities:
        denial = (
            "delegated_capability_not_held_by_user"
            if application is not None and required <= application.capabilities
            else "capability_not_granted"
        )
        return PrincipalDenial(denial, False)
    if not requested <= effective.portfolio_scope:
        return PrincipalDenial("portfolio_outside_scope", False)
    return None


def _resolve_verified(claims, authority, required, requested):
    identity = _principal_identity(claims)
    if isinstance(identity, PrincipalDenial):
        return identity
    grants = _trusted_grants(identity, authority)
    if isinstance(grants, PrincipalDenial):
        return grants
    user, application = grants
    effective = _effective_grants(user, application)
    denial = _grant_denial(effective, application, required, requested)
    if denial is not None:
        return denial
    return VerifiedCompositePrincipal(
        identity.kind,
        identity.subject,
        identity.tenant,
        effective.capabilities,
        effective.portfolio_scope,
        identity.credential_id,
        identity.actor,
    )


def resolve_composite_principal(
    credential: str | None,
    *,
    trust: CredentialTrust | None,
    authority: PrincipalAuthority | None,
    now: datetime,
    required_capabilities: frozenset[str],
    requested_portfolios: frozenset[str] = frozenset(),
) -> PrincipalDenial | VerifiedCompositePrincipal:
    if credential is None or not credential.strip():
        return PrincipalDenial("missing_credential", True)
    if trust is None or not trust.expected_issuer or not trust.expected_audience:
        return PrincipalDenial("present_but_unverified", True)
    claims = verify_composite_credential(credential, trust=trust, now=now)
    if isinstance(claims, PrincipalDenial):
        return claims
    return _resolve_verified(claims, authority, required_capabilities, requested_portfolios)
