"""Require complete original historical source projections, never current holdings."""

from app.models.composite_authority import authority_digest
from app.ports.composite_attribution import AttributionAdmissionError


def refuse(code, message):
    raise AttributionAdmissionError(code, message)


def require_unique(values, *, code="SOURCE_UNIVERSE_INCOMPLETE"):
    if not values or len(set(values)) != len(values):
        refuse(code, "Expected source identities must be nonempty and unique.")
    return set(values)


def source_projections(bundle):
    """Explicit v1 normalized wire fields; original array order remains significant."""
    return {
        bundle.membership_pin_id: {
            "membership_revision": bundle.membership_revision,
            "membership_digest": bundle.membership_digest,
            "expected_portfolio_ids": list(bundle.expected_portfolio_ids),
            "members": [row.model_dump(mode="json") for row in bundle.members],
        },
        bundle.group_source_pin_id: {
            "groups": [row.model_dump(mode="json") for row in bundle.groups],
            "member_groups": [row.model_dump(mode="json") for row in bundle.member_groups],
            "expected_group_ids": list(bundle.expected_group_ids),
            "period_start": str(bundle.period_start),
            "period_end": str(bundle.period_end),
            "reporting_currency": bundle.reporting_currency,
            "return_view": bundle.return_view,
            "policy": bundle.policy.model_dump(mode="json"),
            "derivatives_present": bundle.derivatives_present,
        },
        bundle.benchmark_pin_id: {
            "benchmark_id": bundle.benchmark_id,
            "benchmark_revision": bundle.benchmark_revision,
            "period_start": str(bundle.period_start),
            "period_end": str(bundle.period_end),
            "reporting_currency": bundle.reporting_currency,
            "return_view": bundle.return_view,
            "return_basis": bundle.policy.return_basis,
            "fee_basis": bundle.policy.fee_basis,
            "tax_basis": bundle.policy.tax_basis,
            "expected_group_ids": list(bundle.expected_benchmark_group_ids),
            "groups": [
                {"group_id": row.group_id, "weight": row.benchmark_weight, "return": row.benchmark_return}
                for row in bundle.groups
            ],
        },
        bundle.classification_pin_id: {
            "classification_revision": bundle.classification_revision,
            "expected_group_ids": list(bundle.expected_group_ids),
            "member_group_mapping": [
                {"portfolio_id": row.portfolio_id, "group_id": row.group_id} for row in bundle.member_groups
            ],
        },
    }


def require_source_bindings(request, bundle, approval, *, tenant_id):
    _require_request_scope(request, bundle, tenant_id)
    _require_policy(request, bundle.policy)
    _require_approval(bundle, approval)
    _require_source_pins(request, bundle)


def _require_request_scope(request, bundle, tenant_id):
    fields = (
        "composite_id",
        "candidate_id",
        "source_manifest_id",
        "period_start",
        "period_end",
        "reporting_currency",
        "return_view",
    )
    if bundle.tenant_id != tenant_id or any(getattr(bundle, key) != getattr(request, key) for key in fields):
        refuse("SOURCE_SCOPE_CONFLICT", "Original source does not bind the admitted tenant and exact request.")


def _require_policy(request, policy):
    actual = (policy.binding_id, policy.method, policy.return_view, policy.reporting_currency)
    expected = (request.policy_binding_id, request.method, request.return_view, request.reporting_currency)
    if actual != expected:
        refuse("METHOD_POLICY_CONFLICT", "Exact BF purpose policy differs from the request.")
    if policy.effective_from > request.period_start or policy.effective_to < request.period_end:
        refuse("METHOD_POLICY_UNAVAILABLE", "Purpose policy does not cover the requested period.")


def _require_approval(bundle, approval):
    if (
        approval.bundle_digest != authority_digest(bundle.model_dump(mode="json"))
        or approval.evidence_digest != authority_digest({"wire": approval.evidence_wire})
        or approval.policy_digest != authority_digest(bundle.policy.model_dump(mode="json"))
        or approval.canonical_maker == approval.canonical_checker
    ):
        refuse("ATTRIBUTION_PURPOSE_APPROVAL_CONFLICT", "Independent BF approval does not bind this complete original.")
    expected_qualification = (
        "SYNTHETIC_NON_CERTIFYING" if bundle.qualification == "CONTROLLED_SYNTHETIC_ONLY" else "INSTITUTION_APPROVED"
    )
    if approval.qualification != expected_qualification:
        refuse("ATTRIBUTION_PURPOSE_APPROVAL_CONFLICT", "Source and financial approval qualification differ.")


def _require_source_pins(request, bundle):
    pins = {pin.pin_id: pin for pin in bundle.source_pins}
    if len(pins) != len(bundle.source_pins):
        refuse("SOURCE_IDENTITY_CONFLICT", "Duplicate source pin identities are refused.")
    projections = source_projections(bundle)
    if len(projections) != 4 or set(pins) != set(projections) or set(bundle.raw_source_bodies) != set(pins):
        refuse(
            "SOURCE_PIN_INCOMPLETE",
            "Exactly four distinct consumed historical products and original wires are required.",
        )
    if require_unique(bundle.compatible_pin_ids) != set(pins):
        refuse("SOURCE_CUT_CONFLICT", "Source-owned coherent cut omits or adds consumed product pins.")
    for identity, pin in pins.items():
        _require_wire(pin, bundle.raw_source_bodies[identity], projections[identity])
        _require_coverage(request, pin)


def _require_wire(pin, raw, projection):
    if not isinstance(raw, dict) or raw.get("projection") != projection or authority_digest(raw) != pin.payload_digest:
        refuse("SOURCE_WIRE_CONFLICT", "Original wire, projection or payload digest differs.")


def _require_coverage(request, pin):
    if pin.completeness != "COMPLETE" or pin.omitted_component_count != 0:
        refuse("SOURCE_UNIVERSE_INCOMPLETE", "A historical product is incomplete or omits components.")
    if len(require_unique(pin.page_ids)) != pin.expected_page_count:
        refuse("SOURCE_PAGE_INCOMPLETE", "Original source pages leave a gap or duplicate.")
    if pin.coverage_from > request.period_start or pin.coverage_to < request.period_end:
        refuse("SOURCE_HISTORY_UNAVAILABLE", "Historical source does not cover the complete requested period.")
