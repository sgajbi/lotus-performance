"""Bounded deployment artifact registration; callers cannot select expected trust."""

from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.composite_authority import Digest, EvidenceBinding, Identifier, decode_authority_json
from app.models.composite_eligibility_evidence import VerificationRequest

ReceiptCredentialId = Annotated[str, Field(strict=True, min_length=1, max_length=128)]


def _require_dates(first_wire, last_wire):
    first, last = date.fromisoformat(first_wire), date.fromisoformat(last_wire)
    if first > last or first.isoformat() != first_wire or last.isoformat() != last_wire:
        raise ValueError("Artifact registration requires canonical ordered dates")


def _require_port(port):
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Artifact verification endpoint port refused")


def _require_endpoint(endpoint, synthetic_loopback):
    url = urlsplit(endpoint)
    _require_port(url.port)
    if any((url.username, url.password, url.fragment)) or not url.hostname:
        raise ValueError("Artifact verification endpoint identity refused")
    if url.scheme == "https":
        return
    if url.scheme != "http" or not synthetic_loopback or url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Artifact verification requires HTTPS or explicit synthetic loopback")


def _require_signing_keys(jwks):
    keys = jwks.get("keys")
    if not isinstance(keys, list) or not 1 <= len(keys) <= 8:
        raise ValueError("Artifact registration requires a bounded signing-key set")


class ReceiptArtifactRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: Identifier
    composite_id: Identifier
    definition_version: Identifier
    subject_content_hash: Digest
    purpose: Literal["RETURN_METHOD_CALENDAR"]
    method_binding: EvidenceBinding
    effective_from: str
    effective_to: str
    verifier_id: Identifier
    issuer_id: Identifier
    artifact_revision: Identifier
    artifact_digest: Digest
    owner_service: Identifier
    endpoint: str = Field(max_length=2048)
    issuer_uri: str = Field(min_length=1, max_length=2048)
    principal_id: Identifier
    credential_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    jwks: dict
    revoked_credential_ids: list[ReceiptCredentialId] = Field(default_factory=list, max_length=1024)
    synthetic_loopback: bool = False
    posture: Literal["SYNTHETIC_NON_CERTIFYING"] = "SYNTHETIC_NON_CERTIFYING"

    @model_validator(mode="after")
    def bounded_transport_and_scope(self):
        _require_dates(self.effective_from, self.effective_to)
        _require_endpoint(self.endpoint, self.synthetic_loopback)
        _require_signing_keys(self.jwks)
        return self

    def admits(self, request: VerificationRequest) -> bool:
        return (
            request.tenant_id,
            request.composite_id,
            request.definition_version,
            request.subject_content_hash,
            request.purpose,
            request.binding,
            request.claims_digest,
            request.source_product,
        ) == (
            self.tenant_id,
            self.composite_id,
            self.definition_version,
            self.subject_content_hash,
            self.purpose,
            self.method_binding,
            self.method_binding.digest,
            None,
        ) and self.effective_from <= request.effective_from <= request.effective_to <= self.effective_to


class ReceiptVerifierConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    registrations: list[ReceiptArtifactRegistration] = Field(min_length=1, max_length=64)
    timeout_seconds: int = Field(default=5, gt=0, le=30)

    def registration_for(self, request: VerificationRequest) -> ReceiptArtifactRegistration | None:
        matches = [row for row in self.registrations if row.admits(request)]
        return matches[0] if len(matches) == 1 else None


def decode_receipt_verifier_configuration(wire: str) -> ReceiptVerifierConfiguration:
    if len(wire.encode("utf-8")) > 262144:
        raise ValueError("Receipt-verifier configuration exceeds its bounded deployment size")
    try:
        payload = decode_authority_json(wire)
    except RecursionError:
        raise ValueError("Receipt-verifier deployment JSON nesting refused") from None
    return ReceiptVerifierConfiguration.model_validate(payload)
