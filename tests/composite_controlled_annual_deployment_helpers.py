"""Independently fixed public software anchors; never imported by runtime code."""

import base64
import hashlib
from copy import deepcopy

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.models.composite_authority import authority_digest
from tests.composite_controlled_annual_helpers import graph, hash_envelope


def annual_package():
    proof = graph()["finalization"]["year_authority_verification"]
    anchor = {
        "verifier_id": "synthetic-year-verifier",
        "signer_principal_id": "synthetic-year-signer",
        "verifier_principal_id": "synthetic-year-verifier",
        "configuration_digest": "sha256:3bde62abecfb6ee6e1171c3cbfada1f9ba17e657aeae1b593346037147ccc7a9",
        "signer_key_digest": "sha256:03396219237f75a64f12aeb7f39723abf400b160c364980a765dac24aeba2464",
        "verifier_key_digest": "sha256:68894d58f18f2c34d49eb2f4b110e042cd0f3150a4dc39243d7f63bd598c0783",
        "source_public_key_base64": "JUO5L/EJVRFHatyDadtt3JM2ZaEZeN2hQE7hBmypVZ0=",
        "verifier_public_key_base64": "F0VTtFbd38aQjsqxwQH+arIeK6oGF3lbfUOmNIKZP9U=",
        "source_key_valid_from": "2000-01-01T00:00:00.000000Z",
        "source_key_valid_to": "2100-01-01T00:00:00.000000Z",
        "verifier_key_valid_from": "2000-01-01T00:00:00.000000Z",
        "verifier_key_valid_to": "2100-01-01T00:00:00.000000Z",
        "revocation_revision": "current-r1",
        "revocation_digest": "sha256:eaa186f739241e9ce4a5d2492ae02db8bde03037a4cb819a742dd9439d5988cf",
        "source_evidence_digest": "sha256:9995b20de40f1dae249f4c62ec12f32b68175fd39832914ef7b06b1c8f2c6f61",
    }
    return {
        "version": "controlled-annual-deployment.v1",
        "profile": "CONTROLLED_SYNTHETIC_ONLY",
        "revision": "synthetic-retained-r1",
        "tenant_id": "synthetic-tenant",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2100-01-01T00:00:00Z",
        "registrations": [
            {
                "anchor": anchor,
                "request_digest": authority_digest(proof["request"]),
                "proof_digest": "sha256:58b4cb6959f974600d02f1d269f91c6827d6199554a90190862aa533465b903c",
                "proof": deepcopy(proof),
            }
        ],
    }


def resign(proof, seed=19):
    key = Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)
    public = key.public_key().public_bytes_raw()
    proof["verifier_public_key_base64"] = base64.b64encode(public).decode()
    proof["verifier_key_digest"] = "sha256:" + hashlib.sha256(public).hexdigest()
    unsigned = {k: v for k, v in proof.items() if k not in {"content_hash", "verifier_credential"}}
    proof["verifier_credential"] = base64.b64encode(key.sign(authority_digest(unsigned).encode())).decode()
    hash_envelope(proof)
    return proof
