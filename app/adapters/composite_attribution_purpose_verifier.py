"""Exact BF-purpose verification independent of source possession or TWR approval."""

from app.adapters.composite_attribution_configuration import request_scope, verify_registration
from app.adapters.composite_principal_credentials import PrincipalAuthorityUnavailable
from app.models.composite_attribution import AttributionApproval
from app.models.composite_authority import authority_digest, decode_authority_json
from app.ports.composite_attribution import AttributionAdmissionError


class ConfiguredAttributionPurposeVerifier:
    def __init__(self, source):
        self.source = source

    def verify(self, request, bundle):
        registration, configuration = self.source.registration(request, bundle.tenant_id)
        evidence = registration.approval
        digest = authority_digest(bundle.model_dump(mode="json"))
        try:
            verify_registration(
                registration.evidence,
                trust=configuration.producer_trust,
                authority=self.source.authority,
                purpose="COMPOSITE_ATTRIBUTION_SOURCE",
                request_digest=authority_digest(request_scope(request)),
                portfolios=bundle.expected_portfolio_ids,
            )
            if registration.evidence.result_wire != digest:
                raise ValueError("Producer evidence does not bind this source bundle.")
            _, checker = verify_registration(
                evidence,
                trust=configuration.purpose_trust,
                authority=self.source.authority,
                purpose="COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER",
                request_digest=digest,
                portfolios=bundle.expected_portfolio_ids,
            )
            payload = decode_authority_json(evidence.result_wire)
            maker = self.source.authority.actor(payload["maker_subject"], bundle.tenant_id)
            actual = (
                set(payload),
                payload["policy_digest"],
                checker.principal_kind,
                maker.canonical_identity == checker.canonical_identity,
                maker.subject,
                bundle.qualification,
            )
            required = (
                {"maker_subject", "policy_digest"},
                authority_digest(bundle.policy.model_dump(mode="json")),
                "user",
                False,
                registration.evidence.signer_subject,
                "CONTROLLED_SYNTHETIC_ONLY",
            )
            if actual != required:
                raise ValueError("Independent exact-purpose authority is refused.")
        except (ValueError, KeyError, PrincipalAuthorityUnavailable) as exc:
            raise AttributionAdmissionError(
                "ATTRIBUTION_PURPOSE_AUTHORITY_UNAVAILABLE", "Independent BF-purpose evidence is unavailable."
            ) from exc
        wire = evidence.model_dump_json()
        return AttributionApproval(
            purpose="COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER",
            bundle_digest=digest,
            policy_digest=payload["policy_digest"],
            evidence_wire=wire,
            evidence_digest=authority_digest({"wire": wire}),
            canonical_maker=maker.canonical_identity,
            canonical_checker=checker.canonical_identity,
            qualification="SYNTHETIC_NON_CERTIFYING",
        )
