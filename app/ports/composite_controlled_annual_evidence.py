"""Independent retained year trust; no configuration is inferred from the proof."""

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.models.composite_controlled_annual_authority import (
    ControlledYearBasisVerification,
    ControlledYearBasisVerificationRequest,
)
from app.models.composite_eligibility_evidence import _require


@dataclass(frozen=True)
class ControlledYearVerificationExpectation:
    request: ControlledYearBasisVerificationRequest
    verifier_id: str
    signer_principal_id: str
    verifier_principal_id: str
    configuration_digest: str
    signer_key_digest: str
    verifier_key_digest: str
    source_public_key_base64: str
    source_key_valid_from: str
    source_key_valid_to: str
    verifier_key_valid_from: str
    verifier_key_valid_to: str
    revocation_revision: str
    revocation_digest: str
    source_evidence_digest: str


@dataclass(frozen=True)
class VerifiedControlledYearEvidence:
    proof: ControlledYearBasisVerification
    expectation: ControlledYearVerificationExpectation


class ControlledYearVerificationPort(Protocol):
    def verify(self, request: ControlledYearBasisVerificationRequest) -> VerifiedControlledYearEvidence | None: ...


class UnavailableControlledYearVerification:
    def verify(self, request: ControlledYearBasisVerificationRequest) -> None:
        return None


def controlled_year_verifier() -> ControlledYearVerificationPort:
    """Source/key/enrollment trust needs a separately admitted release adapter."""
    return UnavailableControlledYearVerification()


def admit_controlled_year_verification(proof, result) -> ControlledYearBasisVerification:
    _require(isinstance(result, VerifiedControlledYearEvidence), "COMPOSITE_YEAR_VERIFICATION_UNAVAILABLE")
    verified = ControlledYearBasisVerification.model_validate(result.proof.model_dump())
    expected = result.expectation
    _require(verified == proof and expected.request == proof.request, "COMPOSITE_YEAR_VERIFICATION_BINDING_MISMATCH")
    fields = (
        "verifier_id",
        "signer_principal_id",
        "verifier_principal_id",
        "configuration_digest",
        "signer_key_digest",
        "verifier_key_digest",
        "revocation_revision",
        "revocation_digest",
        "source_evidence_digest",
    )
    _require(
        all(getattr(verified, name) == getattr(expected, name) for name in fields),
        "COMPOSITE_YEAR_VERIFICATION_TRUST_MISMATCH",
    )
    _verify_original_signature(verified, expected.source_public_key_base64)
    _verify_key_windows(verified, expected)
    return verified


def _verify_key_windows(proof, expected) -> None:
    source_issued = datetime.fromisoformat(proof.basis_mapping.basis.actual_issued_at)
    verifier_issued = datetime.fromisoformat(proof.admitted_at)
    for instant, first, last in (
        (source_issued, expected.source_key_valid_from, expected.source_key_valid_to),
        (verifier_issued, expected.verifier_key_valid_from, expected.verifier_key_valid_to),
    ):
        start, end = datetime.fromisoformat(first), datetime.fromisoformat(last)
        _require(
            start.utcoffset() is not None and end.utcoffset() is not None and start <= instant < end,
            "COMPOSITE_YEAR_VERIFICATION_KEY_WINDOW_MISMATCH",
        )


def _verify_original_signature(proof, public_key_base64: str) -> None:
    try:
        key = base64.b64decode(public_key_base64, validate=True)
        _require(
            len(key) == 32 and base64.b64encode(key).decode() == public_key_base64,
            "COMPOSITE_YEAR_SOURCE_SIGNATURE_INVALID",
        )
        _require(
            "sha256:" + hashlib.sha256(key).hexdigest() == proof.signer_key_digest,
            "COMPOSITE_YEAR_SOURCE_SIGNATURE_INVALID",
        )
        mapping = proof.basis_mapping
        Ed25519PublicKey.from_public_bytes(key).verify(
            base64.b64decode(mapping.original_credential, validate=True),
            base64.b64decode(mapping.raw_original_base64, validate=True),
        )
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("COMPOSITE_YEAR_SOURCE_SIGNATURE_INVALID") from exc
