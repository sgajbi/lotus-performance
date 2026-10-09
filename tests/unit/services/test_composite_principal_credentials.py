import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.adapters.composite_principal_credentials import (
    CredentialTrust,
    PrincipalAuthorityUnavailable,
    PrincipalDenial,
    PrincipalGrants,
    VerifiedCompositePrincipal,
    resolve_composite_principal,
    verify_composite_credential,
)
from app.adapters.composite_result_candidate_storage import CAPTURE_CAPABILITY

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "principal_credentials"
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
CAPABILITY = CAPTURE_CAPABILITY


class Authority:
    def __init__(
        self,
        *,
        revoked_ids=(),
        revoked_subjects=(),
        member=True,
        capabilities=(CAPABILITY,),
        portfolios=("portfolio-a",),
        application_caps=(CAPABILITY,),
        application_portfolios=("portfolio-a",),
        unavailable=None,
    ):
        self.revoked_ids, self.revoked_subjects, self.member = revoked_ids, revoked_subjects, member
        self.user_grants = PrincipalGrants(frozenset(capabilities), frozenset(portfolios))
        self.app_grants = PrincipalGrants(frozenset(application_caps), frozenset(application_portfolios))
        self.unavailable = unavailable
        self.calls = []

    def _call(self, operation):
        self.calls.append(operation)
        if operation == self.unavailable:
            raise PrincipalAuthorityUnavailable()

    def revoked(self, subject, credential_id):
        self._call("revoked")
        return subject in self.revoked_subjects or credential_id in self.revoked_ids

    def tenant_member(self, subject, tenant):
        self._call("member")
        return self.member

    def grants(self, subject, tenant):
        self._call("grants")
        return self.user_grants

    def application_grants(self, application, tenant):
        self._call("application")
        return self.app_grants


def _resolve(credential, trust, authority, **kwargs):
    return resolve_composite_principal(
        credential, trust=trust, authority=authority, now=NOW, required_capabilities=frozenset({CAPABILITY}), **kwargs
    )


@pytest.mark.parametrize(
    "name",
    [
        "valid.user",
        "valid.service",
        "valid.delegated",
        "denial.wrong_issuer",
        "denial.wrong_audience",
        "denial.unknown_key_id",
        "denial.revoked_principal",
        "denial.present_but_unverified",
        "denial.not_yet_valid",
        "denial.missing_credential",
        "denial.malformed_credential",
        "denial.expired_credential",
        "denial.algorithm_none",
    ],
)
def test_actual_platform_signed_vector_outcome(name):
    vector = json.loads((FIXTURES / f"{name}.json").read_text())
    inputs = vector["verification_inputs"]
    trust = CredentialTrust(
        inputs["expected_issuer"], inputs["expected_audience"], json.loads((FIXTURES / "jwks.json").read_text())
    )
    authority = Authority(revoked_ids=inputs["revoked_credential_ids"], revoked_subjects=inputs["revoked_subjects"])
    outcome = _resolve(vector["credential"], trust, authority)
    assert (outcome.denial_class if isinstance(outcome, PrincipalDenial) else "verified") == vector["expected_outcome"]
    if isinstance(outcome, PrincipalDenial) and name != "denial.revoked_principal":
        assert authority.calls == []


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@pytest.fixture
def signed_credential():
    key = Ed25519PrivateKey.generate()
    trust = CredentialTrust(
        "https://isolated-issuer.test",
        "lotus-performance",
        {
            "keys": [
                {
                    "kid": "isolated-test",
                    "alg": "EdDSA",
                    "kty": "OKP",
                    "crv": "Ed25519",
                    "x": _encode(key.public_key().public_bytes_raw()),
                }
            ]
        },
    )

    def mint(**changes):
        claims = {
            "iss": trust.expected_issuer,
            "aud": trust.expected_audience,
            "exp": int(NOW.timestamp()) + 600,
            "nbf": int(NOW.timestamp()) - 60,
            "sub": "user:a",
            "tenant": "tenant-a",
            "principal_kind": "user",
            "jti": "credential-a",
            **changes,
        }
        wire = (
            _encode(json.dumps({"alg": "EdDSA", "kid": "isolated-test"}).encode())
            + "."
            + _encode(json.dumps(claims).encode())
        )
        return wire + "." + _encode(key.sign(wire.encode()))

    return trust, mint


@pytest.mark.parametrize("operation", ["revoked", "member", "grants", "application"])
def test_trusted_authority_unavailable_refuses(signed_credential, operation):
    trust, mint = signed_credential
    outcome = _resolve(mint(principal_kind="delegated", act="app:a"), trust, Authority(unavailable=operation))
    assert outcome == PrincipalDenial("grant_store_unavailable", False)


@pytest.mark.parametrize(
    "authority,changes,portfolios,denial",
    [
        (None, {}, (), "grant_store_unavailable"),
        (Authority(member=False), {}, (), "tenant_not_a_member"),
        (Authority(capabilities=()), {"capabilities": [CAPABILITY]}, (), "capability_not_granted"),
        (
            Authority(capabilities=()),
            {"principal_kind": "delegated", "act": "app:a"},
            (),
            "delegated_capability_not_held_by_user",
        ),
        (Authority(application_caps=()), {"principal_kind": "delegated", "act": "app:a"}, (), "capability_not_granted"),
        (
            Authority(application_portfolios=()),
            {"principal_kind": "delegated", "act": "app:a"},
            ("portfolio-a",),
            "portfolio_outside_scope",
        ),
        (Authority(), {}, ("portfolio-b",), "portfolio_outside_scope"),
        (Authority(revoked_subjects=("user:a",)), {}, (), "revoked_principal"),
    ],
)
def test_actual_grants_refuse_instead_of_narrowing(signed_credential, authority, changes, portfolios, denial):
    trust, mint = signed_credential
    outcome = _resolve(mint(**changes), trust, authority, requested_portfolios=frozenset(portfolios))
    assert isinstance(outcome, PrincipalDenial) and outcome.denial_class == denial


def test_registered_performance_audience_and_delegated_intersection(signed_credential):
    trust, mint = signed_credential
    outcome = _resolve(
        mint(principal_kind="delegated", act="app:a"),
        trust,
        Authority(capabilities=(CAPABILITY, "other"), portfolios=("portfolio-a", "portfolio-b")),
        requested_portfolios=frozenset({"portfolio-a"}),
    )
    assert isinstance(outcome, VerifiedCompositePrincipal)
    assert outcome.capabilities == frozenset({CAPABILITY})
    assert outcome.portfolio_scope == frozenset({"portfolio-a"})
    assert outcome.subject == "user:a" and outcome.delegated_actor == "app:a"
    assert _resolve(mint(aud="lotus-gateway"), trust, Authority()) == PrincipalDenial("wrong_audience", True)
    assert _resolve(mint(), None, Authority()) == PrincipalDenial("present_but_unverified", True)


@pytest.mark.parametrize(
    "changes,denial",
    [
        ({"exp": True}, "expired_credential"),
        ({"exp": int(NOW.timestamp())}, "expired_credential"),
        ({"nbf": "tomorrow"}, "expired_credential"),
        ({"aud": {"audience": "lotus-performance"}}, "wrong_audience"),
        ({"sub": " user:a"}, "malformed_credential"),
        ({"tenant": ""}, "malformed_credential"),
        ({"jti": None}, "malformed_credential"),
        ({"principal_kind": "delegated"}, "malformed_credential"),
    ],
)
def test_signed_invalid_claims_do_not_become_authority(signed_credential, changes, denial):
    trust, mint = signed_credential
    authority = Authority()
    assert _resolve(mint(**changes), trust, authority).denial_class == denial
    assert authority.calls == []


@pytest.mark.parametrize("encoding", ["unused_bits", "padding"])
def test_noncanonical_signature_encoding_refuses_before_current_authority(signed_credential, encoding):
    trust, mint = signed_credential
    wire = mint()
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    altered = wire + "=" if encoding == "padding" else wire[:-1] + alphabet[alphabet.index(wire[-1]) + 1]
    original_signature, altered_signature = wire.rsplit(".", 1)[1], altered.rsplit(".", 1)[1]
    assert base64.urlsafe_b64decode(original_signature + "==") == base64.urlsafe_b64decode(altered_signature + "==")
    authority = Authority()
    assert _resolve(altered, trust, authority) == PrincipalDenial("malformed_credential", True)
    assert not authority.calls


@pytest.mark.parametrize("header", ['{"alg":"EdDSA","kid":"isolated-test","kid":"other"}', "[]"])
def test_nonobject_and_duplicate_signed_json_refuse_before_authority(signed_credential, header):
    trust, mint = signed_credential
    _, payload, signature = mint().split(".")
    authority = Authority()
    assert _resolve(_encode(header.encode()) + "." + payload + "." + signature, trust, authority) == PrincipalDenial(
        "malformed_credential", True
    )
    assert not authority.calls


@pytest.mark.parametrize("credential", [None, "", " "])
def test_public_signature_verifier_missing_input_is_a_typed_denial(signed_credential, credential):
    trust, _ = signed_credential
    assert verify_composite_credential(credential, trust=trust, now=NOW) == PrincipalDenial("missing_credential", True)


@pytest.mark.parametrize(
    "key_change",
    ["duplicate", "wrong_type", "wrong_curve", "encryption_use", "invalid_public_bytes", "missing_key_set"],
)
def test_signed_credential_requires_one_usable_trusted_signing_key(signed_credential, key_change):
    trust, mint = signed_credential
    jwks = json.loads(json.dumps(trust.jwks))
    if key_change == "duplicate":
        jwks["keys"].append(jwks["keys"][0].copy())
    elif key_change == "missing_key_set":
        jwks = {}
    else:
        field, value = {
            "wrong_type": ("kty", "RSA"),
            "wrong_curve": ("crv", "X25519"),
            "encryption_use": ("use", "enc"),
            "invalid_public_bytes": ("x", "AQ"),
        }[key_change]
        jwks["keys"][0][field] = value
    authority = Authority()
    outcome = _resolve(mint(), CredentialTrust(trust.expected_issuer, trust.expected_audience, jwks), authority)
    assert outcome == PrincipalDenial("unknown_key_id", True)
    assert authority.calls == []
