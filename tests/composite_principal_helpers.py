"""Isolated signing keys and trusted test-only ports, never deployment authority."""

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.adapters.composite_principal_credentials import CredentialTrust, PrincipalAuthorityUnavailable, PrincipalGrants
from app.composite_principal_admission import CompositePrincipalDeployment


class TestPrincipalAuthority:
    __test__ = False

    def __init__(self, tenant, portfolios):
        self.tenant = tenant
        self.portfolios = frozenset(portfolios)
        self.capabilities = frozenset({"operations.runtime.manage", "operations.runtime.read"})
        self.revoked_ids = set()
        self.available = True

    def _require_available(self):
        if not self.available:
            raise PrincipalAuthorityUnavailable()

    def revoked(self, subject, credential_id):
        self._require_available()
        return credential_id in self.revoked_ids

    def tenant_member(self, subject, tenant):
        self._require_available()
        return tenant == self.tenant

    def grants(self, subject, tenant):
        self._require_available()
        return PrincipalGrants(self.capabilities, self.portfolios)

    def application_grants(self, application, tenant):
        return self.grants(application, tenant)


def install_principal_deployment(monkeypatch, application, *, tenant, portfolios):
    key = Ed25519PrivateKey.generate()

    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    trust = CredentialTrust(
        "https://isolated-principal.test",
        "lotus-performance",
        {
            "keys": [
                {
                    "kid": "test-only",
                    "kty": "OKP",
                    "crv": "Ed25519",
                    "alg": "EdDSA",
                    "x": encode(key.public_key().public_bytes_raw()),
                }
            ]
        },
    )
    authority = TestPrincipalAuthority(tenant, portfolios)
    monkeypatch.setattr(
        application.state,
        "composite_principal_deployment",
        CompositePrincipalDeployment(trust, authority),
        raising=False,
    )

    def mint(**changes):
        now = int(datetime.now(UTC).timestamp())
        claims = {
            "iss": trust.expected_issuer,
            "aud": trust.expected_audience,
            "sub": "verified-test-maker",
            "tenant": tenant,
            "principal_kind": "user",
            "jti": "test-" + uuid4().hex,
            "nbf": now - 30,
            "exp": now + 600,
            **changes,
        }
        wire = (
            encode(json.dumps({"alg": "EdDSA", "kid": "test-only"}).encode())
            + "."
            + encode(json.dumps(claims).encode())
        )
        return wire + "." + encode(key.sign(wire.encode()))

    return authority, mint
