"""Read immutable producer artifacts through the existing BF source protocol."""

import hashlib
import json
from threading import Lock

from app.adapters.composite_attribution_configuration import read_bounded, request_scope, verify_registration
from app.adapters.composite_principal_credentials import PrincipalAuthorityUnavailable
from app.models.composite_attribution import AttributionSourceBundle
from app.models.composite_authority import authority_digest
from app.ports.composite_attribution import AttributionAdmissionError
from app.services.composite_attribution.source_binding import _require_source_pins


def _financial_object(pairs):
    # BF raw projections contain finite FLOAT64 ratios, unlike authority JSON.
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate financial artifact JSON key.")
    return result


def decode_bundle(wire):
    payload = json.loads(wire, object_pairs_hook=_financial_object)
    authority_digest(payload)  # Reject nonfinite values, including nested raw bodies.
    return AttributionSourceBundle.model_validate(payload)


class ConfiguredAttributionSource:
    def __init__(self, configuration, authority):
        self.authority = authority
        self._bundles = {}
        self._lock = Lock()

    def _original_wire(self, registration):
        with self._lock:
            manifest = registration.request.source_manifest_id
            if manifest not in self._bundles:
                wire = read_bounded(registration.artifact_path)
                if "sha256:" + hashlib.sha256(wire.encode("utf-8")).hexdigest() != registration.artifact_digest:
                    raise ValueError("Original source artifact bytes differ from deployment custody.")
                self._bundles[manifest] = wire
            return self._bundles[manifest]

    def _validate(self, registration, bundle, configuration):
        scope = request_scope(registration.request)
        bundle_scope = bundle.model_dump(
            mode="json", include=set(scope) - {"metric_id", "method", "precision_mode", "policy_binding_id"}
        )
        expected = {key: value for key, value in scope.items() if key in bundle_scope}
        actual = (
            bundle_scope,
            bundle.tenant_id,
            bundle.policy.binding_id,
            bundle.qualification,
            bundle.expected_portfolio_ids,
            registration.request.precision_mode,
        )
        required = (
            expected,
            configuration.tenant_id,
            registration.request.policy_binding_id,
            "CONTROLLED_SYNTHETIC_ONLY",
            registration.expected_portfolio_ids,
            "FLOAT64",
        )
        if actual != required:
            raise ValueError("Source artifact does not bind its exact controlled registration.")
        if registration.evidence.result_wire != wire_identity(bundle):
            raise ValueError("Producer evidence does not bind the complete source bundle.")
        verify_registration(
            registration.evidence,
            trust=configuration.producer_trust,
            authority=self.authority,
            purpose="COMPOSITE_ATTRIBUTION_SOURCE",
            request_digest=authority_digest(scope),
            portfolios=bundle.expected_portfolio_ids,
        )
        _require_source_pins(registration.request, bundle)

    def registration(self, request, tenant_id):
        try:
            configuration = self.authority.configuration()
        except PrincipalAuthorityUnavailable as exc:
            raise AttributionAdmissionError(
                "SOURCE_AUTHORITY_UNAVAILABLE", "Controlled source registration has expired."
            ) from exc
        matches = [row for row in configuration.sources if row.request.source_manifest_id == request.source_manifest_id]
        if tenant_id != configuration.tenant_id or not matches:
            raise AttributionAdmissionError("SOURCE_AUTHORITY_UNAVAILABLE", "Pinned attribution source is unavailable.")
        registration = matches[0]
        if request_scope(request) != request_scope(registration.request):
            raise AttributionAdmissionError(
                "SOURCE_SCOPE_CONFLICT", "Source registration differs from exact request scope."
            )
        return registration, configuration

    def read_population_scope(self, request, *, tenant_id):
        registration, configuration = self.registration(request, tenant_id)
        try:
            verify_registration(
                registration.evidence,
                trust=configuration.producer_trust,
                authority=self.authority,
                purpose="COMPOSITE_ATTRIBUTION_SOURCE",
                request_digest=authority_digest(request_scope(request)),
                portfolios=registration.expected_portfolio_ids,
            )
        except (ValueError, PrincipalAuthorityUnavailable) as exc:
            raise AttributionAdmissionError(
                "SOURCE_AUTHORITY_UNAVAILABLE", "Source population evidence is unavailable."
            ) from exc
        return registration.expected_portfolio_ids

    def read_pinned(self, request, *, tenant_id):
        registration, configuration = self.registration(request, tenant_id)
        try:
            bundle = decode_bundle(self._original_wire(registration))
            self._validate(registration, bundle, configuration)
        except (ValueError, OSError, PrincipalAuthorityUnavailable) as exc:
            raise AttributionAdmissionError(
                "SOURCE_AUTHORITY_UNAVAILABLE", "Pinned source evidence is unavailable."
            ) from exc
        return bundle


def wire_identity(bundle):
    return authority_digest(bundle.model_dump(mode="json"))
