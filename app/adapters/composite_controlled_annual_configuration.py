"""Closed operator custody for retained synthetic annual verification only."""

import base64
import hashlib
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.adapters.composite_attribution_configuration import MAX_ARTIFACT_BYTES, DeploymentWire, require_unique
from app.models.composite_authority import Digest, Identifier, Instant, authority_digest, decode_authority_json
from app.models.composite_controlled_annual_authority import ControlledYearBasisVerification
from app.ports.composite_controlled_annual_evidence import (
    ControlledYearVerificationExpectation,
    VerifiedControlledYearEvidence,
    admit_controlled_year_verification,
)

CONFIG_ENV = "LOTUS_COMPOSITE_CONTROLLED_ANNUAL_DEPLOYMENT"


class AnnualTrustAnchor(DeploymentWire):
    verifier_id: Identifier
    signer_principal_id: Identifier
    verifier_principal_id: Identifier
    configuration_digest: Digest
    signer_key_digest: Digest
    verifier_key_digest: Digest
    source_public_key_base64: str = Field(strict=True, min_length=44, max_length=44)
    verifier_public_key_base64: str = Field(strict=True, min_length=44, max_length=44)
    source_key_valid_from: Instant
    source_key_valid_to: Instant
    verifier_key_valid_from: Instant
    verifier_key_valid_to: Instant
    revocation_revision: Identifier
    revocation_digest: Digest
    source_evidence_digest: Digest

    @model_validator(mode="after")
    def independent_public_keys(self):
        for public, digest in (
            (self.source_public_key_base64, self.signer_key_digest),
            (self.verifier_public_key_base64, self.verifier_key_digest),
        ):
            raw = base64.b64decode(public, validate=True)
            if len(raw) != 32 or base64.b64encode(raw).decode() != public:
                raise ValueError("Canonical public Ed25519 key required.")
            if "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Public anchor digest mismatch.")
        if self.signer_principal_id == self.verifier_principal_id or self.signer_key_digest == self.verifier_key_digest:
            raise ValueError("Independent annual principals and keys required.")
        return self


class RetainedAnnualRegistration(DeploymentWire):
    anchor: AnnualTrustAnchor
    request_digest: Digest
    proof_digest: Digest
    proof: ControlledYearBasisVerification

    @model_validator(mode="after")
    def exact_retained_registration(self):
        if self.request_digest != authority_digest(self.proof.request.model_dump(mode="json")):
            raise ValueError("Registered annual request digest mismatch.")
        if self.proof_digest != self.proof.content_hash:
            raise ValueError("Registered annual proof digest mismatch.")
        if self.anchor.verifier_public_key_base64 != self.proof.verifier_public_key_base64:
            raise ValueError("Independent annual verifier key mismatch.")
        admit_controlled_year_verification(self.proof, self.evidence())
        return self

    def evidence(self):
        fields = self.anchor.model_dump(exclude={"verifier_public_key_base64"})
        expected = ControlledYearVerificationExpectation(request=self.proof.request.model_copy(deep=True), **fields)
        return VerifiedControlledYearEvidence(self.proof.model_copy(deep=True), expected)


class AnnualVerificationConfiguration(DeploymentWire):
    version: Literal["controlled-annual-deployment.v1"]
    profile: Literal["CONTROLLED_SYNTHETIC_ONLY"]
    revision: Identifier
    tenant_id: Identifier
    valid_from: datetime
    valid_until: datetime
    revoked_request_digests: frozenset[Digest] = frozenset()
    registrations: tuple[RetainedAnnualRegistration, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def bounded_scope(self):
        if self.valid_from.utcoffset() is None or self.valid_until.utcoffset() is None:
            raise ValueError("Annual deployment validity requires timezones.")
        if self.valid_from >= self.valid_until:
            raise ValueError("Annual deployment validity interval is empty.")
        require_unique([row.request_digest for row in self.registrations])
        if any(row.proof.request.tenant_id != self.tenant_id for row in self.registrations):
            raise ValueError("Annual deployment cannot cross tenants.")
        return self


def decode_annual_configuration(wire):
    if len(wire.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError("Annual deployment exceeds its bounded size.")
    return AnnualVerificationConfiguration.model_validate(decode_authority_json(wire))
