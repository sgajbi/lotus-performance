"""Validate resolved source bindings; a digest never supplies owner authority."""

from typing import NoReturn

from app.models.composite_authority import authority_digest
from app.models.composite_pooled_mwr import CompositePooledMWRRequest, PooledSourceBundle, PooledSourcePin
from app.ports.composite_pooled_mwr import PooledSourceAdmissionError


def refuse(code: str, message: str, *, unavailable: bool = False) -> NoReturn:
    raise PooledSourceAdmissionError(code, message, availability="UNAVAILABLE" if unavailable else "REFUSED")


def require_pooled_day_basis(request) -> None:
    if request.annualization.basis != "ACT/365":
        refuse("METHOD_DATE_BASIS_UNSUPPORTED", "Pooled XIRR currently admits the reviewed ACT/365 convention only.")


def require_source_bindings(
    request: CompositePooledMWRRequest, bundle: PooledSourceBundle, *, tenant_id: str
) -> dict[str, PooledSourcePin]:
    """Check a trusted reader's original bundle before pooling any money.

    The reader independently verifies source-owner/policy authority. These local
    identity, digest and coverage checks cannot replace that verification.
    Compatibility references bind retained per-source vectors; there is no
    universal source epoch or requirement that every source use the same cut ID.
    """
    identities = (
        (bundle.tenant_id, tenant_id),
        (bundle.composite_id, request.composite_id),
        (bundle.source_manifest_id, request.source_manifest_id),
        (bundle.period_start, request.period_start),
        (bundle.period_end, request.period_end),
        (bundle.reporting_currency, request.reporting_currency),
    )
    if any(actual != expected for actual, expected in identities):
        refuse("SOURCE_CUT_CONFLICT", "Resolved source scope differs from the admitted request.")
    pins = _require_source_vector(request, bundle)
    _require_population(bundle, pins)
    _require_policy(request, bundle)
    return pins


def _require_source_vector(request, bundle):
    pins = {pin.pin_id: pin for pin in bundle.source_pins}
    if not pins or len(pins) != len(bundle.source_pins):
        refuse("SOURCE_IDENTITY_UNAVAILABLE", "Source pin identities must be nonempty and unique.")
    if set(pins) != set(bundle.raw_source_bodies):
        refuse("SOURCE_CUT_UNAVAILABLE", "Every source pin requires its complete original body.", unavailable=True)
    if len(bundle.compatible_pin_ids) != len(pins) or set(bundle.compatible_pin_ids) != set(pins):
        refuse(
            "SOURCE_CUT_UNAVAILABLE",
            "The owner compatibility binding must cover the entire selected vector.",
            unavailable=True,
        )
    for pin in pins.values():
        _require_complete_pin(pin, bundle.raw_source_bodies[pin.pin_id], request)
    return pins


def _require_population(bundle, pins):
    if bundle.population_source_pin_id not in pins or not bundle.population_complete:
        refuse("MISSING_POPULATION_COVERAGE", "Complete pinned population coverage is required.", unavailable=True)
    expected = set(bundle.expected_portfolio_ids)
    if len(expected) != len(bundle.expected_portfolio_ids) or len(expected) != bundle.expected_population_count:
        refuse(
            "MISSING_POPULATION_COVERAGE",
            "Expected population identities and control count disagree.",
            unavailable=True,
        )


def _require_complete_pin(pin, body, request):
    if (
        pin.completeness != "COMPLETE"
        or pin.coverage_from > request.period_start
        or pin.coverage_to < request.period_end
    ):
        refuse("SOURCE_CUT_UNAVAILABLE", "Source coverage is incomplete for the requested interval.", unavailable=True)
    if len(set(pin.page_ids)) != pin.expected_page_count or len(pin.page_ids) != pin.expected_page_count:
        refuse("SOURCE_CUT_UNAVAILABLE", "All unique pinned source pages must be retained.", unavailable=True)
    if not isinstance(body, dict) or authority_digest(body) != pin.payload_digest:
        refuse("SOURCE_CUT_CONFLICT", "Retained source bytes do not match their selected payload binding.")


def _require_policy(request, bundle):
    require_pooled_day_basis(request)
    policy = bundle.policy
    if (
        policy.binding_id != request.policy_binding_id
        or policy.method != request.method
        or policy.return_view != request.return_view
    ):
        refuse(
            "APPLICABILITY_UNAVAILABLE",
            "Resolved policy does not bind the elected method and fee view.",
            unavailable=True,
        )
    if policy.day_count_basis != request.annualization.basis or policy.fallback_policy != request.fallback_policy:
        refuse("METHOD_POLICY_MISMATCH", "Date basis and fallback must match the resolved policy election.")
    if policy.boundary_flow_policy == "UNSUPPORTED":
        refuse("BOUNDARY_POLICY_UNAVAILABLE", "Boundary values and flows lack an admitted treatment.", unavailable=True)
