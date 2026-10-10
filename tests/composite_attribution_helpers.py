"""Controlled financial observations; these do not qualify a real source owner."""

from types import SimpleNamespace
from uuid import uuid4

from app.models.composite_attribution import AttributionApproval, AttributionSourceBundle, CompositeAttributionRequest
from app.models.composite_authority import authority_digest
from app.services.composite_attribution.source_binding import source_projections

DIGEST = "sha256:" + "a" * 64


def seal(bundle):
    """Bind raw normalized wire and verifier receipt after a deliberate source change."""
    bodies = {key: {"projection": value} for key, value in source_projections(bundle).items()}
    pins = tuple(
        pin.model_copy(update={"payload_digest": authority_digest(bodies[pin.pin_id])}) for pin in bundle.source_pins
    )
    bundle = bundle.model_copy(update={"raw_source_bodies": bodies, "source_pins": pins})
    approval = AttributionApproval(
        purpose="COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER",
        bundle_digest=authority_digest(bundle.model_dump(mode="json")),
        policy_digest=authority_digest(bundle.policy.model_dump(mode="json")),
        evidence_digest=authority_digest({"wire": "synthetic-unit-fixture"}),
        evidence_wire="synthetic-unit-fixture",
        canonical_maker="source-maker",
        canonical_checker="independent-checker",
        qualification="SYNTHETIC_NON_CERTIFYING",
    )
    return bundle, approval


def controlled_financial_case(*, calculation_id=None, candidate_id=None):
    request = CompositeAttributionRequest(
        calculation_id=calculation_id or uuid4(),
        composite_id="CMP-OR17",
        candidate_id=candidate_id or uuid4(),
        source_manifest_id="manifest-1",
        policy_binding_id="policy-1",
        period_start="2026-01-01",
        period_end="2026-01-31",
        reporting_currency="USD",
        return_view="GROSS",
    )
    scope = dict(period_start="2026-01-01", period_end="2026-01-31", reporting_currency="USD", return_view="GROSS")
    bundle = AttributionSourceBundle.model_validate(
        {
            **scope,
            "tenant_id": "tenant-a",
            "composite_id": request.composite_id,
            "candidate_id": request.candidate_id,
            "source_manifest_id": request.source_manifest_id,
            "original_response_digest": DIGEST,
            "vector_digest": DIGEST,
            "membership_revision": "membership-1",
            "membership_digest": DIGEST,
            "classification_revision": "classification-1",
            "classification_pin_id": "classification",
            "benchmark_id": "BENCHMARK",
            "benchmark_revision": "benchmark-1",
            "benchmark_pin_id": "benchmark",
            "group_source_pin_id": "economics",
            "membership_pin_id": "population",
            "expected_portfolio_ids": ["member-a"],
            "expected_group_ids": ["g1", "g2"],
            "expected_benchmark_group_ids": ["g1", "g2"],
            "compatible_pin_ids": ["population", "economics", "benchmark", "classification"],
            "compatibility_reference": "approved-cut-1",
            "derivatives_present": False,
            "qualification": "CONTROLLED_SYNTHETIC_ONLY",
            "members": [
                {
                    "portfolio_id": "member-a",
                    "status": "INCLUDED",
                    "effective_from": "2026-01-01",
                    "effective_to": "2026-01-31",
                    "reason": "approved",
                    "composite_weight": 1.0,
                    "actual_return": 0.068,
                    "source_row_id": "member-row",
                }
            ],
            "member_groups": [
                {
                    "portfolio_id": "member-a",
                    "group_id": group,
                    "member_weight": weight,
                    "actual_return": ret,
                    "source_row_id": group + "-member",
                }
                for group, weight, ret in (("g1", 0.6, 0.10), ("g2", 0.4, 0.02))
            ],
            "groups": [
                {
                    "group_id": group,
                    "portfolio_weight": weight,
                    "benchmark_weight": 0.5,
                    "portfolio_return": ret,
                    "benchmark_return": bench,
                    "source_row_id": group + "-pooled",
                }
                for group, weight, ret, bench in (("g1", 0.6, 0.10, 0.08), ("g2", 0.4, 0.02, 0.03))
            ],
            "source_pins": [
                {
                    "pin_id": pin,
                    "owner": "controlled-owner",
                    "product_name": pin,
                    "revision": pin + "-1",
                    "source_cut_id": "cut-1",
                    "payload_digest": DIGEST,
                    "coverage_from": "2026-01-01",
                    "coverage_to": "2026-01-31",
                    "page_ids": ["page-1"],
                    "expected_page_count": 1,
                    "omitted_component_count": 0,
                    "completeness": "COMPLETE",
                }
                for pin in ("population", "economics", "benchmark", "classification")
            ],
            "policy": {
                "binding_id": "policy-1",
                "revision": "policy-revision-1",
                "purpose": "COMPOSITE_SINGLE_PERIOD_BRINSON_FACHLER",
                "aggregation": "SOURCE_APPROVED_POOLED_COMPOSITE_GROUP_ECONOMICS",
                "method": request.method,
                "weight_basis": "BEGINNING_CAPITAL",
                "return_basis": "SINGLE_PERIOD_ARITHMETIC",
                "return_view": "GROSS",
                "reporting_currency": "USD",
                "fee_basis": "gross-no-fees",
                "tax_basis": "source-tax-basis",
                "tolerance": 1e-12,
                "effective_from": "2026-01-01",
                "effective_to": "2026-01-31",
            },
            "raw_source_bodies": {},
        }
    )
    bundle, approval = seal(bundle)
    period = SimpleNamespace(
        period_start=request.period_start,
        period_end=request.period_end,
        reporting_currency="USD",
        return_view="GROSS",
        status="READY",
        return_value=0.068,
        member_contributions=[SimpleNamespace(portfolio_id="member-a", beginning_asset_weight=1.0, return_value=0.068)],
    )
    original = SimpleNamespace(
        candidate_id=request.candidate_id,
        tenant_id="tenant-a",
        original_response_digest=DIGEST,
        response=SimpleNamespace(
            composite_id=request.composite_id,
            periods=[period],
            selection_manifest=SimpleNamespace(windows=[SimpleNamespace(membership_content_hash=DIGEST)]),
        ),
    )
    vector = SimpleNamespace(vector_digest=DIGEST, windows=[object()])
    return request, bundle, approval, original, vector
