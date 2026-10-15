"""Bounded deployment custody; financial DTOs and public requests stay unchanged."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.adapters.composite_principal_credentials import (
    CredentialTrust,
    PrincipalAuthorityUnavailable,
    PrincipalDenial,
    PrincipalGrants,
    _public_key,
    verify_composite_credential,
)
from app.models.composite_attribution import CompositeAttributionRequest
from app.models.composite_authority import Digest, Identifier, authority_digest, decode_authority_json

CONFIG_ENV = "LOTUS_COMPOSITE_ATTRIBUTION_DEPLOYMENT"
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024


class DeploymentWire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def require_unique(values):
    if len(set(values)) != len(values):
        raise ValueError("Deployment identities must be unique.")


def public_key_rows(jwks):
    keys = jwks.get("keys")
    if set(jwks) != {"keys"} or not isinstance(keys, list) or not 1 <= len(keys) <= 8:
        raise ValueError("Bounded public signing keys are required.")
    return _identified_public_keys(keys)


def _identified_public_keys(keys):
    if any(not isinstance(key, dict) for key in keys):
        raise ValueError("Signing keys must be public objects.")
    ids = [key.get("kid") for key in keys]
    if any(not isinstance(identity, str) for identity in ids):
        raise ValueError("Signing key identities must be strings.")
    require_unique(ids)
    return keys


class PublicTrust(DeploymentWire):
    issuer: Identifier
    audience: Literal["lotus-performance"] = "lotus-performance"
    jwks: dict

    @model_validator(mode="after")
    def public_keys_only(self):
        for key in public_key_rows(self.jwks):
            if set(key) - {"kid", "kty", "crv", "alg", "use", "x"} or _public_key(self.trust(), key.get("kid")) is None:
                raise ValueError("Only valid public Ed25519 keys are admitted.")
        return self

    def trust(self):
        return CredentialTrust(self.issuer, self.audience, json.loads(self.model_dump_json())["jwks"])


class ActorRegistration(DeploymentWire):
    subject: Identifier
    canonical_identity: Identifier
    tenant_id: Identifier
    capabilities: frozenset[Literal["operations.runtime.manage", "operations.runtime.read"]]
    portfolio_scope: frozenset[Identifier]
    principal_kind: Literal["user", "service", "delegated"] = "user"


class SignedRegistration(DeploymentWire):
    purpose: Identifier
    request_digest: Digest
    result_wire: str = Field(min_length=1, max_length=1048576)
    credential: str = Field(min_length=1, max_length=16384)
    signer_subject: Identifier


class SourceRegistration(DeploymentWire):
    request: CompositeAttributionRequest
    expected_portfolio_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=1000)
    artifact_path: str = Field(min_length=1, max_length=2048)
    artifact_digest: Digest
    evidence: SignedRegistration
    approval: SignedRegistration

    @model_validator(mode="after")
    def bounded_bf_evidence(self):
        if not Path(self.artifact_path).is_absolute():
            raise ValueError("Source artifact paths must be operator-resolved absolute paths.")
        if len(self.approval.result_wire.encode("utf-8")) > 16384:
            raise ValueError("BF approval evidence exceeds its retained wire bound.")
        return self


class SourceAuthorityRegistration(DeploymentWire):
    kind: Literal["APPROVAL", "PROVIDER", "RECEIPT"]
    evidence: SignedRegistration


class AttributionConfiguration(DeploymentWire):
    version: Literal["v1"] = "v1"
    profile: Literal["CONTROLLED_SYNTHETIC_ONLY"]
    revision: Identifier
    tenant_id: Identifier
    valid_until: datetime
    expected_portfolio_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=1000)
    principal_trust: PublicTrust
    producer_trust: PublicTrust
    purpose_trust: PublicTrust
    original_authority_trust: PublicTrust
    actors: tuple[ActorRegistration, ...] = Field(min_length=2, max_length=64)
    revoked_credential_ids: frozenset[Identifier] = frozenset()
    sources: tuple[SourceRegistration, ...] = Field(default=(), max_length=64)
    source_authorities: tuple[SourceAuthorityRegistration, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def isolated_scope(self):
        if self.valid_until.tzinfo is None:
            raise ValueError("Deployment validity must carry its timezone.")
        require_unique([actor.subject for actor in self.actors])
        require_unique(self.expected_portfolio_ids)
        require_unique([row.request.source_manifest_id for row in self.sources])
        if any(actor.tenant_id != self.tenant_id for actor in self.actors):
            raise ValueError("Controlled deployment cannot cross tenant boundaries.")
        _require_registration_identities(self.sources, self.source_authorities, self.expected_portfolio_ids)
        return self


def _require_registration_identities(sources, authorities, population):
    for source in sources:
        require_unique(source.expected_portfolio_ids)
        if source.expected_portfolio_ids != population:
            raise ValueError("Source registration must bind the complete deployment population.")
    keys = [(row.kind, row.evidence.purpose, row.evidence.request_digest) for row in authorities]
    require_unique(keys)


def decode_configuration(wire):
    if len(wire.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError("Deployment configuration exceeds its bounded size.")
    return AttributionConfiguration.model_validate(decode_authority_json(wire))


def read_bounded(path, *, maximum=MAX_ARTIFACT_BYTES):
    if not Path(path).is_absolute():
        raise ValueError("Deployment paths must be operator-resolved absolute paths.")
    with Path(path).open("rb") as stream:
        wire = stream.read(maximum + 1)
    if len(wire) > maximum:
        raise ValueError("Deployment artifact exceeds its bounded size.")
    return wire.decode("utf-8")


def request_scope(request):
    return request.model_dump(
        mode="json",
        exclude={"calculation_id", "official_scope_id", "official_revision", "correction_of_calculation_id"},
    )


class ConfiguredPrincipalAuthority:
    """An expiring synthetic grant snapshot, not an institutional grant store."""

    def __init__(self, configuration, *, now=None):
        self._wire = configuration.model_dump_json()
        self.now = now or (lambda: datetime.now(UTC))

    def configuration(self):
        value = AttributionConfiguration.model_validate_json(self._wire)
        if self.now() >= value.valid_until:
            raise PrincipalAuthorityUnavailable("Controlled deployment has expired.")
        return value

    def actor(self, subject, tenant):
        configuration = self.configuration()
        matches = [row for row in configuration.actors if (row.subject, row.tenant_id) == (subject, tenant)]
        if len(matches) != 1:
            raise PrincipalAuthorityUnavailable("Principal registration is unavailable.")
        return matches[0]

    def revoked(self, subject, credential_id):
        configuration = self.configuration()
        return (
            subject not in {row.subject for row in configuration.actors}
            or credential_id in configuration.revoked_credential_ids
        )

    def tenant_member(self, subject, tenant_id):
        return any((row.subject, row.tenant_id) == (subject, tenant_id) for row in self.configuration().actors)

    def grants(self, subject, tenant_id):
        actor = self.actor(subject, tenant_id)
        return PrincipalGrants(actor.capabilities, actor.portfolio_scope)

    def application_grants(self, application, tenant_id):
        actor = self.actor(application, tenant_id)
        if actor.principal_kind != "service":
            raise PrincipalAuthorityUnavailable("Application registration is unavailable.")
        return self.grants(application, tenant_id)


def verify_registration(registration, *, trust, authority, purpose, request_digest, portfolios=()):
    configuration = authority.configuration()
    claims = verify_composite_credential(registration.credential, trust=trust.trust(), now=authority.now())
    expected = {
        "purpose": purpose,
        "request_digest": request_digest,
        "result_digest": authority_digest({"wire": registration.result_wire}),
        "qualification": "SYNTHETIC_NON_CERTIFYING",
        "tenant": configuration.tenant_id,
        "sub": registration.signer_subject,
        "portfolio_scope_digest": authority_digest({"portfolio_ids": sorted(portfolios)}),
    }
    if isinstance(claims, PrincipalDenial) or any(claims.get(key) != value for key, value in expected.items()):
        raise ValueError("Signed deployment evidence is refused.")
    if (registration.purpose, registration.request_digest) != (purpose, request_digest):
        raise ValueError("Signed registration has another purpose or request.")
    return claims, _require_signer(registration, claims, configuration, authority, portfolios)


def _require_signer(registration, claims, configuration, authority, portfolios):
    credential_id = claims.get("jti")
    if (
        not isinstance(credential_id, str)
        or not credential_id
        or authority.revoked(registration.signer_subject, credential_id)
    ):
        raise ValueError("Signed deployment credential is revoked or absent.")
    actor = authority.actor(registration.signer_subject, configuration.tenant_id)
    if "operations.runtime.manage" not in actor.capabilities or not set(portfolios) <= actor.portfolio_scope:
        raise ValueError("Signed evidence actor lacks the exact controlled scope.")
    return actor
