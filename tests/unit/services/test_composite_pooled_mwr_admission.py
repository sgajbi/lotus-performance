"""Complete controlled source fixtures and refusal controls; no live qualification."""

from copy import deepcopy

import pytest

from app.models.composite_authority import authority_digest
from app.models.composite_pooled_mwr import CompositePooledMWRRequest, PooledSourceBundle
from app.ports.composite_pooled_mwr import PooledSourceAdmissionError
from app.services.composite_pooled_mwr.source_binding import require_source_bindings


def controlled_source_payload():
    bodies = {"population": {"controlled_revision": "population-v1"}, "money": {"controlled_revision": "money-v1"}}
    pins = [
        {
            "pin_id": key,
            "owner": "CONTROLLED_TEST_OWNER",
            "product_name": key,
            "product_version": "v1",
            "revision": key + "-v1",
            "source_cut_id": key + "-cut",
            "payload_digest": authority_digest(body),
            "compatibility_group": key + "-owner-local",
            "coverage_from": "2025-01-01",
            "coverage_to": "2026-01-01",
            "completeness": "COMPLETE",
            "page_ids": [key + "-page-1"],
            "expected_page_count": 1,
        }
        for key, body in bodies.items()
    ]
    membership = [
        {
            "portfolio_id": member,
            "effective_from": "2025-01-01",
            "effective_to": "2026-01-01",
            "status": "INCLUDED",
            "source_row_id": member + "-membership",
            "reason_code": "CONTROLLED_INCLUDED",
        }
        for member in ("member-a", "member-b")
    ]
    valuations = [
        {
            "portfolio_id": member,
            "economic_date": day,
            "role": role,
            "amount": amount,
            "currency": "USD",
            "source_pin_id": "money",
            "source_row_id": member + "-" + role,
            "timing": timing,
        }
        for member, opening, terminal in (("member-a", "50", "60"), ("member-b", "50", "50"))
        for day, role, amount, timing in (
            ("2025-01-01", "OPENING", opening, "BOD"),
            ("2026-01-01", "TERMINAL", terminal, "EOD"),
        )
    ]
    payload = {
        "tenant_id": "controlled-tenant",
        "composite_id": "CONTROLLED_POOL",
        "source_manifest_id": "controlled-original-v1",
        "definition_revision": "definition-v1",
        "definition_hash": "controlled-definition-hash",
        "membership_revision": "membership-v1",
        "membership_hash": "controlled-membership-hash",
        "population_source_pin_id": "population",
        "compatibility_reference": "controlled-cross-owner-compatibility-v1",
        "compatible_pin_ids": list(bodies),
        "period_start": "2025-01-01",
        "period_end": "2026-01-01",
        "reporting_currency": "USD",
        "expected_portfolio_ids": ["member-a", "member-b"],
        "expected_population_count": 2,
        "population_complete": True,
        "membership": membership,
        "valuations": valuations,
        "flows": [],
        "flow_coverage": [
            {
                "portfolio_id": member,
                "coverage_from": "2025-01-01",
                "coverage_to": "2026-01-01",
                "source_pin_id": "money",
                "complete": True,
                "active_event_ids": [],
                "explicitly_empty": True,
            }
            for member in ("member-a", "member-b")
        ],
        "source_pins": pins,
        "policy": {
            "binding_id": "controlled-xirr-policy-v1",
            "owner": "CONTROLLED_POLICY_OWNER",
            "revision": "v1",
            "content_hash": "controlled-policy-hash",
            "applicability_reference": "controlled-applicability-v1",
            "method": "XIRR:v1",
            "return_view": "GROSS",
            "fee_basis": "GROSS_BEFORE_FEES",
            "tax_basis": "CONTROLLED_TAX_BASIS",
            "sign_convention": "PORTFOLIO_IN_POSITIVE",
            "date_basis": "EFFECTIVE_DATE",
            "opening_timing": "BOD",
            "terminal_timing": "EOD",
            "boundary_flow_policy": "VALUES_EXCLUDE_BOUNDARY_FLOWS",
            "transfer_policy": "NO_INTERNAL_TRANSFERS",
            "entry_exit_policy": "EXPLICIT_BOUNDARY_CAPITAL",
            "day_count_basis": "ACT/365",
            "fallback_policy": "REQUIRE_XIRR",
        },
        "qualification": "CONTROLLED_SYNTHETIC_ONLY",
        "institutional_attestation": "NOT_ATTESTED",
        "raw_source_bodies": bodies,
    }
    bodies["population"].update(
        {
            key: payload[key]
            for key in (
                "definition_revision",
                "membership_revision",
                "expected_portfolio_ids",
                "expected_population_count",
                "membership",
            )
        }
    )
    bodies["money"].update({key: payload[key] for key in ("valuations", "flows", "flow_coverage")})
    bodies["population"]["policy"] = deepcopy(payload["policy"])
    for pin in pins:
        pin["payload_digest"] = authority_digest(bodies[pin["pin_id"]])
    return payload


def controlled_request():
    return CompositePooledMWRRequest(
        composite_id="CONTROLLED_POOL",
        period_start="2025-01-01",
        period_end="2026-01-01",
        reporting_currency="USD",
        return_view="GROSS",
        source_manifest_id="controlled-original-v1",
        policy_binding_id="controlled-xirr-policy-v1",
    )


def test_source_binding_accepts_complete_controlled_vector_with_distinct_owner_cuts():
    bundle = PooledSourceBundle.model_validate(controlled_source_payload())
    pins = require_source_bindings(controlled_request(), bundle, tenant_id="controlled-tenant")
    assert set(pins) == {"population", "money"}
    assert pins["population"].source_cut_id != pins["money"].source_cut_id
    assert bundle.qualification == "CONTROLLED_SYNTHETIC_ONLY"
    assert bundle.institutional_attestation == "NOT_ATTESTED"


@pytest.mark.parametrize(
    "path,value,code,availability",
    [
        (("tenant_id",), "foreign-tenant", "SOURCE_CUT_CONFLICT", "REFUSED"),
        (("source_manifest_id",), "latest", "SOURCE_CUT_CONFLICT", "REFUSED"),
        (("population_complete",), False, "MISSING_POPULATION_COVERAGE", "UNAVAILABLE"),
        (("expected_population_count",), 3, "MISSING_POPULATION_COVERAGE", "UNAVAILABLE"),
        (("compatible_pin_ids",), ["money"], "SOURCE_CUT_UNAVAILABLE", "UNAVAILABLE"),
        (("raw_source_bodies", "money"), {"changed": True}, "SOURCE_CUT_CONFLICT", "REFUSED"),
        (("source_pins", 1, "completeness"), "UNAVAILABLE", "SOURCE_CUT_UNAVAILABLE", "UNAVAILABLE"),
        (("source_pins", 0, "coverage_to"), "2025-12-31", "SOURCE_CUT_UNAVAILABLE", "UNAVAILABLE"),
        (("source_pins", 0, "page_ids"), ["page1", "page1"], "SOURCE_CUT_UNAVAILABLE", "UNAVAILABLE"),
        (("policy", "binding_id"), "wrong-policy", "APPLICABILITY_UNAVAILABLE", "UNAVAILABLE"),
        (("policy", "return_view"), "NET_ACTUAL", "APPLICABILITY_UNAVAILABLE", "UNAVAILABLE"),
        (("policy", "day_count_basis"), "ACT/ACT", "METHOD_POLICY_MISMATCH", "REFUSED"),
        (("policy", "fallback_policy"), "ALLOW_MODIFIED_DIETZ", "METHOD_POLICY_MISMATCH", "REFUSED"),
        (("policy", "boundary_flow_policy"), "UNSUPPORTED", "BOUNDARY_POLICY_UNAVAILABLE", "UNAVAILABLE"),
    ],
)
def test_source_binding_refuses_incomplete_or_conflicting_original_evidence(path, value, code, availability):
    payload = deepcopy(controlled_source_payload())
    parent = payload
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    bundle = PooledSourceBundle.model_validate(payload)
    with pytest.raises(PooledSourceAdmissionError) as error:
        require_source_bindings(controlled_request(), bundle, tenant_id="controlled-tenant")
    assert error.value.code == code
    assert error.value.availability == availability
