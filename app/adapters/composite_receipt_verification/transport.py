"""Read-only bounded consumer transport with independently configured artifact expectations."""

import os
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from app.adapters.composite_receipt_verification.configuration import ReceiptVerifierConfiguration
from app.adapters.composite_receipt_verification.credentials import verify_receipt_credential
from app.models.composite_authority import decode_authority_json
from app.models.composite_eligibility_evidence import VerificationReceipt, VerificationRequest
from app.ports.composite_external_evidence import (
    CompositeVerificationExpectation,
    UnavailableCompositeEvidence,
    VerifiedCompositeEvidence,
    admit_verified_receipt,
)


class ConfiguredCompositeReceiptVerifier:
    def __init__(self, configuration: ReceiptVerifierConfiguration, *, transport=None, now=None):
        self.configuration = configuration
        self.transport = transport
        self.now = now or (lambda: datetime.now(timezone.utc))

    def verify(self, request: VerificationRequest) -> VerifiedCompositeEvidence | UnavailableCompositeEvidence:
        registration = self.configuration.registration_for(request)
        if registration is None:
            return UnavailableCompositeEvidence()
        credential = os.environ.get(registration.credential_env)
        if not credential or len(credential) > 8192 or "\r" in credential or "\n" in credential:
            return UnavailableCompositeEvidence()
        try:
            envelope = self._read(registration, request, credential)
            return self._verified_result(registration, request, envelope)
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError, ValidationError, RecursionError):
            return UnavailableCompositeEvidence()

    def _verified_result(self, registration, request, envelope):
        if (
            set(envelope) != {"owner_service", "payload", "credential"}
            or envelope["owner_service"] != registration.owner_service
        ):
            return UnavailableCompositeEvidence()
        payload = envelope["payload"]
        if not isinstance(payload, dict) or not verify_receipt_credential(
            envelope["credential"], registration=registration, request=request, payload=payload, now=self.now()
        ):
            return UnavailableCompositeEvidence()
        receipt = VerificationReceipt.model_validate(payload)
        expectation = CompositeVerificationExpectation(
            request.model_copy(deep=True),
            registration.verifier_id,
            registration.issuer_id,
            registration.artifact_revision,
            registration.artifact_digest,
        )
        result = VerifiedCompositeEvidence(receipt, expectation)
        admit_verified_receipt(expectation, result, allow_synthetic=True)
        return result

    def _read(self, registration, request, credential):
        with httpx.Client(
            timeout=self.configuration.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        ) as client:
            with client.stream(
                "POST",
                registration.endpoint,
                json=request.model_dump(mode="json"),
                headers={"Authorization": "Bearer " + credential, "Accept": "application/json"},
            ) as response:
                if (
                    response.status_code != 200
                    or sum(len(key) + len(value) for key, value in response.headers.multi_items()) > 16384
                ):
                    raise ValueError("Receipt verification transport refused")
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise ValueError("Receipt verification body exceeds its bound")
                return decode_authority_json(body.decode("utf-8"))
