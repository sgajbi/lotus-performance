"""Offline control artifact authoring only; never imported by runtime startup."""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.adapters.composite_attribution_configuration import (
    AttributionConfiguration,
    ConfiguredPrincipalAuthority,
    request_scope,
)
from app.models.composite_authority import authority_digest
from tests.composite_attribution_helpers import controlled_financial_case


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class DeploymentControl:
    def __init__(self, tmp_path, *, request=None, bundle=None):
        self.key = Ed25519PrivateKey.generate()
        self.now = datetime.now(UTC)
        self.request, self.bundle = (request, bundle) if request is not None else controlled_financial_case()[:2]
        self.bundle_path = tmp_path / "source.json"
        wire = self.bundle.model_dump_json()
        self.bundle_path.write_text(wire, encoding="utf-8")
        trust = {
            "issuer": "isolated-deployment-issuer",
            "audience": "lotus-performance",
            "jwks": {
                "keys": [
                    {
                        "kid": "control",
                        "kty": "OKP",
                        "crv": "Ed25519",
                        "x": encode(self.key.public_key().public_bytes_raw()),
                    }
                ]
            },
        }
        self.payload = {
            "version": "v1",
            "profile": "CONTROLLED_SYNTHETIC_ONLY",
            "revision": "controlled-v1",
            "tenant_id": self.bundle.tenant_id,
            "valid_until": (self.now + timedelta(hours=1)).isoformat(),
            "expected_portfolio_ids": list(self.bundle.expected_portfolio_ids),
            **{
                name: trust
                for name in ("principal_trust", "producer_trust", "purpose_trust", "original_authority_trust")
            },
            "actors": [self.actor("maker"), self.actor("checker")],
            "sources": [
                {
                    "request": self.request.model_dump(mode="json"),
                    "expected_portfolio_ids": list(self.bundle.expected_portfolio_ids),
                    "artifact_path": str(self.bundle_path),
                    "artifact_digest": "sha256:" + hashlib.sha256(wire.encode()).hexdigest(),
                    "evidence": self.registration(
                        "COMPOSITE_ATTRIBUTION_SOURCE",
                        authority_digest(request_scope(self.request)),
                        authority_digest(self.bundle.model_dump(mode="json")),
                        signer="maker",
                    ),
                    "approval": self.registration(
                        "COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER",
                        authority_digest(self.bundle.model_dump(mode="json")),
                        json.dumps(
                            {
                                "maker_subject": "maker",
                                "policy_digest": authority_digest(self.bundle.policy.model_dump(mode="json")),
                            }
                        ),
                    ),
                }
            ],
            "source_authorities": [],
        }
        self.config_path = tmp_path / "deployment.json"

    def actor(self, subject):
        return {
            "subject": subject,
            "canonical_identity": "canonical-" + subject,
            "tenant_id": self.bundle.tenant_id,
            "capabilities": ["operations.runtime.manage", "operations.runtime.read"],
            "portfolio_scope": list(self.bundle.expected_portfolio_ids),
            "principal_kind": "user",
        }

    def mint(self, **claims):
        payload = {
            "iss": "isolated-deployment-issuer",
            "aud": "lotus-performance",
            "sub": "checker",
            "tenant": self.bundle.tenant_id,
            "principal_kind": "user",
            "jti": uuid4().hex,
            "nbf": int(self.now.timestamp()) - 10,
            "exp": int(self.now.timestamp()) + 3600,
            **claims,
        }
        wire = (
            encode(json.dumps({"alg": "EdDSA", "kid": "control"}).encode()) + "." + encode(json.dumps(payload).encode())
        )
        return wire + "." + encode(self.key.sign(wire.encode()))

    def registration(self, purpose, digest, result_wire, *, signer="checker", **claims):
        return {
            "purpose": purpose,
            "request_digest": digest,
            "result_wire": result_wire,
            "signer_subject": signer,
            "credential": self.mint(
                sub=signer,
                purpose=purpose,
                request_digest=digest,
                result_digest=authority_digest({"wire": result_wire}),
                qualification="SYNTHETIC_NON_CERTIFYING",
                portfolio_scope_digest=authority_digest({"portfolio_ids": sorted(self.bundle.expected_portfolio_ids)}),
                **claims,
            ),
        }

    def resign(self, evidence, **changes):
        segment = evidence["credential"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        evidence["credential"] = self.mint(**{**claims, **changes})

    def configuration(self):
        return AttributionConfiguration.model_validate(self.payload)

    def authority(self):
        return ConfiguredPrincipalAuthority(self.configuration(), now=lambda: self.now)

    def write(self):
        self.config_path.write_text(json.dumps(self.payload), encoding="utf-8")
        return str(self.config_path)


def reset_installation(monkeypatch):
    from app.adapters import composite_attribution_bootstrap as bootstrap
    from app.adapters import composite_attribution_deployment as deployment
    from app.adapters import composite_source_authority_deployment as original

    monkeypatch.setattr(bootstrap, "_installed", None)
    monkeypatch.setattr(deployment, "_installed", False)
    monkeypatch.setattr(
        deployment,
        "_deployment",
        deployment.CompositeAttributionDeployment(
            deployment.UnavailableAttributionSource(),
            deployment.UnavailableAttributionAuthority(),
        ),
    )
    monkeypatch.setattr(original, "_deployment", None)


def original_registrations(control, fixture, monkeypatch):
    """Author signed test registrations from actual retained dependency requests."""
    from app.adapters.composite_result_authority.vector import captured_vector
    from app.adapters.composite_source_authority_deployment import original_request_digest
    from app.ports import composite_external_evidence as ports
    from app.services.composite_materialization import authority_policy

    records = {}

    class ObservedAuthority:
        def __init__(self, delegate):
            self.delegate = delegate

        def verify(self, request):
            subject = request.definition.created_by
            if subject not in {row["subject"] for row in control.payload["actors"]}:
                control.payload["actors"].append(control.actor(subject))
            digest = original_request_digest(request)
            records[("APPROVAL", request.purpose, digest)] = {
                "kind": "APPROVAL",
                "evidence": control.registration(
                    request.purpose,
                    digest,
                    json.dumps({"maker_subject": subject}),
                ),
            }
            return self.delegate.verify(request)

        def resolve(self, request):
            digest = original_request_digest(request)
            records[("PROVIDER", "PROVIDER_REGISTRATION", digest)] = {
                "kind": "PROVIDER",
                "evidence": control.registration(
                    "PROVIDER_REGISTRATION",
                    digest,
                    json.dumps({"registration_digest": request.registry_digest}),
                ),
            }
            return self.delegate.resolve(request)

    with monkeypatch.context() as observing:
        for name in ("authority_approval_verifier", "eligibility_approval_verifier", "method_approval_verifier"):
            owner = getattr(ports, name)()
            observing.setattr(ports, name, lambda owner=owner: ObservedAuthority(owner))
        owner = authority_policy.provider_trust_resolver()
        observing.setattr(authority_policy, "provider_trust_resolver", lambda: ObservedAuthority(owner))
        with fixture.store._session() as session:
            captured_vector(session, fixture.principal("maker"), control.bundle.candidate_id)
    return list(records.values())
