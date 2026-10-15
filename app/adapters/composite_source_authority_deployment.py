"""Exact signed original-source registrations, subordinate to existing policy."""

from fastapi.encoders import jsonable_encoder

from app.adapters.composite_attribution_configuration import verify_registration
from app.adapters.composite_principal_credentials import PrincipalAuthorityUnavailable
from app.models.composite_authority import authority_digest, decode_authority_json
from app.models.composite_eligibility_evidence import VerificationReceipt
from app.ports import composite_external_evidence as ports

_deployment = None


def original_request_digest(request):
    payload = jsonable_encoder(request)
    if isinstance(request, ports.CompositeApprovalRequest):
        # Rehydration uses the materialization identity as calculation_id. That
        # operational attempt identity is not part of original financial custody.
        payload["command"] = jsonable_encoder(request.command.immutable_payload())
    return authority_digest(payload)


class ConfiguredSourceAuthorities:
    def __init__(self, authority):
        self.authority = authority

    def _read(self, kind, purpose, request):
        configuration = self.authority.configuration()
        digest = original_request_digest(request)
        matches = [
            row.evidence
            for row in configuration.source_authorities
            if (row.kind, row.evidence.purpose, row.evidence.request_digest) == (kind, purpose, digest)
        ]
        if len(matches) != 1 or request.tenant_id != configuration.tenant_id:
            raise ValueError("Exact original authority registration is unavailable.")
        evidence = matches[0]
        portfolios = configuration.expected_portfolio_ids
        _, signer = verify_registration(
            evidence,
            trust=configuration.original_authority_trust,
            authority=self.authority,
            purpose=purpose,
            request_digest=digest,
            portfolios=portfolios,
        )
        return decode_authority_json(evidence.result_wire), signer

    def verify(self, request):
        """Approval and receipt protocols intentionally retain distinct return types."""
        try:
            if isinstance(request, ports.CompositeApprovalRequest):
                return self._approval(request)
            return self._receipt(request)
        except (ValueError, KeyError, PrincipalAuthorityUnavailable):
            return (
                False if isinstance(request, ports.CompositeApprovalRequest) else ports.UnavailableCompositeEvidence()
            )

    def _approval(self, request):
        allowed = {
            "COMPOSITE_ECONOMIC_AUTHORITY_PROFILE",
            "ELIGIBILITY_POLICY_EVALUATION",
            "RETURN_METHOD_CALENDAR",
            "ELIGIBILITY_POLICY",
            "COMPOSITE_MONTHLY_MEMBERSHIP_APPROVAL",
        }
        if (
            request.purpose not in allowed
            or request.definition.authority_approval.evidence_kind != "SYNTHETIC_UNSIGNED"
        ):
            return False
        payload, checker = self._read("APPROVAL", request.purpose, request)
        maker = self.authority.actor(payload["maker_subject"], request.tenant_id)
        return (
            set(payload) == {"maker_subject"}
            and checker.principal_kind == "user"
            and maker.subject == request.definition.created_by
            and maker.canonical_identity != checker.canonical_identity
        )

    def _receipt(self, request):
        payload, _ = self._read("RECEIPT", request.purpose, request)
        receipt = VerificationReceipt.model_validate(payload)
        expectation = ports.CompositeVerificationExpectation(
            request.model_copy(deep=True),
            receipt.verifier_id,
            receipt.issuer_id,
            receipt.artifact_revision,
            receipt.artifact_digest,
        )
        result = ports.VerifiedCompositeEvidence(receipt, expectation)
        ports.admit_verified_receipt(expectation, result, allow_synthetic=True)
        return result

    def resolve(self, request):
        from app.services.composite_materialization.authority_policy import ProviderTrustResolution

        try:
            payload, _ = self._read("PROVIDER", "PROVIDER_REGISTRATION", request)
            if payload == {"registration_digest": request.registry_digest}:
                return ProviderTrustResolution("SYNTHETIC_TEST_ONLY", "CONTROLLED_DEPLOYMENT", request.registry_digest)
        except (ValueError, KeyError, PrincipalAuthorityUnavailable):
            pass
        return ProviderTrustResolution("UNAVAILABLE", "COMPOSITE_PROVIDER_TRUST_UNAVAILABLE")


def install_source_authorities(deployment):
    global _deployment
    if _deployment is not None:
        raise RuntimeError("Composite original authority deployment is already installed.")
    _deployment = deployment


def configured_source_authorities():
    return _deployment
