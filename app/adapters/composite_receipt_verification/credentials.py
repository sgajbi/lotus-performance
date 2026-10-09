"""Reuse bounded Ed25519 signature primitives; receipt claims are not principal grants."""

from datetime import datetime

from app.adapters.composite_principal_credentials import CredentialTrust, PrincipalDenial, _json_segment, _signed_claims
from app.adapters.composite_receipt_verification.configuration import ReceiptArtifactRegistration
from app.models.composite_authority import authority_digest
from app.models.composite_eligibility_evidence import VerificationRequest


def _header_allowed(credential):
    try:
        header_wire, _, _ = credential.split(".")
        if len(header_wire) > 2048:
            return False
        header = _json_segment(header_wire)
        if set(header) - {"alg", "kid", "typ"} or header.get("typ") not in (None, "JWT"):
            return False
    except (ValueError, TypeError, UnicodeError):
        return False
    return True


def _identity_allowed(claims, registration, request):
    return tuple(claims.get(key) for key in ("iss", "aud", "sub", "tenant_id", "operation", "delegated_actor")) == (
        registration.issuer_uri,
        "lotus-performance",
        registration.principal_id,
        request.tenant_id,
        "composite-evidence.verify",
        None,
    )


def _time_allowed(claims, now):
    instant = int(now.timestamp())
    expiry, not_before = claims.get("exp"), claims.get("nbf")
    return (
        type(expiry) is int and type(not_before) is int and instant < expiry <= instant + 300 and not_before <= instant
    )


def _token_allowed(claims, registration):
    identity = claims.get("jti")
    return (
        isinstance(identity, str) and 0 < len(identity) <= 128 and identity not in registration.revoked_credential_ids
    )


def _content_allowed(claims, request, payload):
    return (claims.get("request_hash"), claims.get("payload_hash")) == (
        authority_digest(request.model_dump(mode="json")),
        authority_digest(payload),
    )


def verify_receipt_credential(
    credential, *, registration: ReceiptArtifactRegistration, request: VerificationRequest, payload: dict, now: datetime
) -> bool:
    if not isinstance(credential, str) or len(credential) > 16384 or not _header_allowed(credential):
        return False
    claims = _signed_claims(
        credential, CredentialTrust(registration.issuer_uri, "lotus-performance", registration.jwks)
    )
    if isinstance(claims, PrincipalDenial):
        return False
    return all(
        (
            _identity_allowed(claims, registration, request),
            _time_allowed(claims, now),
            _token_allowed(claims, registration),
            _content_allowed(claims, request, payload),
        )
    )
