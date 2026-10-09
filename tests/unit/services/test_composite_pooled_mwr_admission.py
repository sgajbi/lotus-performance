"""Complete controlled source fixtures and refusal controls; no live qualification."""

from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext

import pytest

from app.models.composite_authority import authority_digest
from app.models.composite_pooled_mwr import CompositePooledMWRRequest, PooledSourceBundle
from app.ports.composite_pooled_mwr import PooledSourceAdmissionError
from app.services.composite_pooled_mwr.admission import admit_pooled_observation
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
            "flow_lifecycle_policy": "OWNER_RESOLVED_CURRENT_EFFECTIVE",
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


def _admit(payload, request=None):
    # These are complete controlled owner fixtures, never a production verifier.
    bodies = payload["raw_source_bodies"]
    bodies["money"].update({key: deepcopy(payload[key]) for key in ("valuations", "flows", "flow_coverage")})
    bodies["population"].update(
        {
            key: deepcopy(payload[key])
            for key in ("membership", "expected_portfolio_ids", "expected_population_count", "policy")
        }
    )
    for pin in payload["source_pins"]:
        pin["payload_digest"] = authority_digest(bodies[pin["pin_id"]])
    return admit_pooled_observation(
        controlled_request() if request is None else request,
        PooledSourceBundle.model_validate(payload),
        tenant_id="controlled-tenant",
    )


def _flow(*, member="member-a", event="flow-a", amount="10", **updates):
    return {
        "portfolio_id": member,
        "event_id": event,
        "amount": amount,
        "economic_date": "2025-07-01",
        "source_date": "2025-07-01",
        "currency": "USD",
        "timing": "BOD",
        "classification": "EXTERNAL",
        "flow_scope": "PORTFOLIO",
        "source_pin_id": "money",
        "identity_namespace": "controlled-events",
        "identity_scope": "PORTFOLIO",
        "revision": "v1",
        "lifecycle_status": "ACTIVE",
        **updates,
    }


def _with_flows(payload, flows):
    payload["flows"] = flows
    unique = {
        (row["portfolio_id"], row["identity_namespace"], row["event_id"], row["revision"]): row
        for row in flows
        if row["lifecycle_status"] == "ACTIVE"
    }
    for coverage in payload["flow_coverage"]:
        coverage["active_event_ids"] = [
            row["event_id"] for row in unique.values() if row["portfolio_id"] == coverage["portfolio_id"]
        ]
        coverage["explicitly_empty"] = not coverage["active_event_ids"]
    return payload


def test_original_or15_admission_retains_exact_control_totals_and_sign_vector():
    observation = _admit(controlled_source_payload())
    assert observation.opening_value == Decimal(100)
    assert observation.terminal_value == Decimal(110)
    assert not observation.portfolio_cash_flows
    assert [(row.economic_date, row.amount) for row in observation.investor_cash_flows] == [
        (date(2025, 1, 1), Decimal(-100)),
        (date(2026, 1, 1), Decimal(110)),
    ]
    assert observation.source_bundle.qualification == "CONTROLLED_SYNTHETIC_ONLY"
    assert observation.per_member_controls["member-a"]["terminal_value"] == "60"


def test_duplicate_and_out_of_order_correction_is_resolved_before_netting():
    original = _flow(amount="9", lifecycle_status="SUPERSEDED")
    corrected = _flow(
        amount="10.000000000000000001", revision="v2", predecessor_event_id="flow-a", predecessor_revision="v1"
    )
    first = _admit(_with_flows(controlled_source_payload(), [corrected, original, deepcopy(corrected)]))
    reordered = _admit(_with_flows(controlled_source_payload(), [original, corrected]))
    assert first.portfolio_cash_flows == reordered.portfolio_cash_flows
    assert first.portfolio_cash_flows[0].amount == Decimal("10.000000000000000001")
    assert first.investor_cash_flows[1].amount == Decimal("-10.000000000000000001")
    assert len(first.portfolio_cash_flows[0].source_event_ids) == 1
    assert len(first.source_bundle.flows) == 3  # No loss of original source evidence.


def test_source_resolved_cancelled_event_requires_positive_empty_coverage():
    payload = _with_flows(controlled_source_payload(), [_flow(lifecycle_status="CANCELLED")])
    assert not _admit(deepcopy(payload)).portfolio_cash_flows
    payload["flow_coverage"][0]["explicitly_empty"] = False
    with pytest.raises(PooledSourceAdmissionError, match="empty"):
        _admit(payload)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"amount": "11"}, "SOURCE_IDENTITY_CONFLICT"),
        ({"revision": "v2"}, "SOURCE_IDENTITY_CONFLICT"),
    ],
)
def test_conflicting_duplicate_or_multiple_active_revisions_refuse(change, code):
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(_with_flows(controlled_source_payload(), [_flow(), _flow(**change)]))
    assert error.value.code == code


@pytest.mark.parametrize(
    "change,code",
    [
        ({"classification": "UNKNOWN"}, "FLOW_CLASSIFICATION_UNAVAILABLE"),
        ({"currency": "EUR"}, "UNSUPPORTED_CURRENCY"),
        ({"economic_date": "2024-12-31"}, "ECONOMIC_DATE_OUTSIDE_WINDOW"),
        ({"source_date": "2025-06-30"}, "FLOW_DATE_POLICY_MISMATCH"),
        ({"predecessor_event_id": "missing", "predecessor_revision": "v0"}, "FLOW_LIFECYCLE_UNAVAILABLE"),
    ],
)
def test_dated_source_flow_refuses_missing_classification_currency_date_or_predecessor(change, code):
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(_with_flows(controlled_source_payload(), [_flow(**change)]))
    assert error.value.code == code


@pytest.mark.parametrize(
    "change,code",
    [
        (("membership", 0, "effective_from", "2025-01-02"), "MISSING_POPULATION_COVERAGE"),
        (("membership", 0, "status", "PENDING"), "APPLICABILITY_UNAVAILABLE"),
        (("flow_coverage", 0, "complete", False), "MISSING_FLOW_COVERAGE"),
        (("flow_coverage", 0, "coverage_to", "2025-12-31"), "MISSING_FLOW_COVERAGE"),
        (("flow_coverage", 0, "explicitly_empty", False), "MISSING_FLOW_COVERAGE"),
        (("valuations", 0, "timing", "EOD"), "BOUNDARY_TIMING_MISMATCH"),
    ],
)
def test_population_boundary_and_empty_flow_coverage_are_independent_requirements(change, code):
    payload = controlled_source_payload()
    collection, index, field, value = change
    payload[collection][index][field] = value
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == code


def test_explicit_historical_exclusion_is_retained_and_not_a_missing_member():
    payload = _with_flows(controlled_source_payload(), [_flow(member="member-b")])
    payload["membership"][1]["status"] = "EXCLUDED"
    payload["valuations"] = [row for row in payload["valuations"] if row["portfolio_id"] != "member-b"]
    result = _admit(payload)
    assert (result.opening_value, result.terminal_value) == (Decimal(50), Decimal(60))
    assert not result.portfolio_cash_flows and len(result.excluded_flow_event_ids) == 1
    assert len(result.source_bundle.expected_portfolio_ids) == 2


def _entry_payload():
    payload = controlled_source_payload()
    old = payload["membership"].pop()
    payload["membership"].extend(
        [
            {**old, "effective_to": "2025-06-30", "status": "EXCLUDED", "source_row_id": "b-excluded"},
            {**old, "effective_from": "2025-07-01", "source_row_id": "b-entered"},
        ]
    )
    opening = next(
        row for row in payload["valuations"] if row["portfolio_id"] == "member-b" and row["role"] == "OPENING"
    )
    opening.update(role="ENTRY", economic_date="2025-07-01", amount="30", source_row_id="b-entry-capital")
    return payload


def test_membership_entry_adds_source_valued_boundary_capital_on_actual_economic_date():
    result = _admit(_entry_payload())
    assert result.opening_value == Decimal(50) and result.terminal_value == Decimal(110)
    assert result.portfolio_cash_flows[0].amount == Decimal(30)
    assert result.investor_cash_flows[1].amount == Decimal(-30)
    assert result.investor_cash_flows[1].economic_date == date(2025, 7, 1)
    assert result.per_member_controls["member-b"]["entry_capital"] == "30"


def test_missing_entry_value_or_unsupported_entry_policy_does_not_infer_capital():
    payload = _entry_payload()
    payload["valuations"] = [row for row in payload["valuations"] if row["role"] != "ENTRY"]
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == "MISSING_BOUNDARY_VALUATION"
    payload = _entry_payload()
    payload["policy"]["entry_exit_policy"] = "UNAVAILABLE"
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == "BOUNDARY_POLICY_UNAVAILABLE"


def _transfer_payload():
    payload = controlled_source_payload()
    payload["policy"]["transfer_policy"] = "SOURCE_LINKED_RECONCILED"
    return _with_flows(
        payload,
        [
            _flow(
                event="transfer-out",
                amount="-10",
                classification="POOL_TRANSFER",
                transfer_group_id="group-1",
                counterparty_portfolio_id="member-b",
            ),
            _flow(
                member="member-b",
                event="transfer-in",
                amount="10",
                classification="POOL_TRANSFER",
                transfer_group_id="group-1",
                counterparty_portfolio_id="member-a",
            ),
        ],
    )


def test_source_linked_internal_transfer_eliminates_only_proven_pair():
    result = _admit(_transfer_payload())
    assert not result.portfolio_cash_flows
    assert len(result.eliminated_transfer_event_ids) == 2
    assert len(result.source_bundle.flows) == 2


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("amount", "9.99", "TRANSFER_LEGS_UNRECONCILED"),
        ("transfer_group_id", "different-group", "TRANSFER_LEGS_UNRECONCILED"),
        ("counterparty_portfolio_id", "member-b", "TRANSFER_LEGS_UNRECONCILED"),
        ("timing", "EOD", "TRANSFER_LEGS_UNRECONCILED"),
    ],
)
def test_same_amount_or_date_is_insufficient_transfer_reconciliation(field, value, code):
    payload = _transfer_payload()
    payload["flows"][1][field] = value
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == code


def test_equal_opposite_external_flows_keep_both_source_identities_after_exact_netting():
    result = _admit(
        _with_flows(
            controlled_source_payload(),
            [_flow(amount="-10"), _flow(member="member-b", event="different-event", amount="10")],
        )
    )
    assert result.portfolio_cash_flows[0].amount == 0
    assert len(result.portfolio_cash_flows[0].source_event_ids) == 2
    assert len(result.investor_cash_flows[1].source_event_ids) == 2
    assert not result.eliminated_transfer_event_ids


def test_exact_source_money_uses_existing_bounded_context_under_low_caller_precision():
    payload = controlled_source_payload()
    payload["valuations"][0]["amount"] = "100000000000000000000000.1234567890123456789"
    with localcontext() as context:
        context.prec = 6
        result = _admit(payload)
    assert str(result.opening_value) == "100000000000000000000050.1234567890123456789"
    assert str(result.investor_cash_flows[0].amount) == "-100000000000000000000050.1234567890123456789"


def test_extreme_representation_refuses_existing_monetary_domain_without_rounding():
    payload = controlled_source_payload()
    payload["valuations"][0]["amount"] = "0E-10000"
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == "MONETARY_DOMAIN_UNSUPPORTED"


@pytest.mark.parametrize(
    "collection,index,code",
    [
        ("valuations", 1, "MISSING_BOUNDARY_VALUATION"),
        ("membership", 1, "MISSING_POPULATION_COVERAGE"),
        ("flow_coverage", 1, "MISSING_FLOW_COVERAGE"),
    ],
)
def test_missing_expected_member_boundary_or_coverage_does_not_shrink_population(collection, index, code):
    payload = controlled_source_payload()
    payload[collection].pop(index)
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == code


def test_membership_exit_uses_source_eod_capital_on_inclusive_exit_date():
    payload = controlled_source_payload()
    old = payload["membership"].pop()
    payload["membership"].extend(
        [
            {**old, "effective_to": "2025-06-30", "source_row_id": "b-before-exit"},
            {**old, "effective_from": "2025-07-01", "status": "EXCLUDED", "source_row_id": "b-after-exit"},
        ]
    )
    terminal = next(
        row for row in payload["valuations"] if row["portfolio_id"] == "member-b" and row["role"] == "TERMINAL"
    )
    terminal.update(role="EXIT", economic_date="2025-06-30", amount="55", source_row_id="b-exit-capital")
    result = _admit(payload)
    assert (result.opening_value, result.terminal_value) == (Decimal(100), Decimal(60))
    assert result.portfolio_cash_flows[0].amount == Decimal(-55)
    assert result.investor_cash_flows[1].amount == Decimal(55)
    assert result.investor_cash_flows[1].economic_date == date(2025, 6, 30)


def test_lifecycle_cycle_cannot_convert_corrupt_history_to_zero_flows():
    flows = [
        _flow(revision="v1", lifecycle_status="SUPERSEDED", predecessor_event_id="flow-a", predecessor_revision="v2"),
        _flow(revision="v2", lifecycle_status="SUPERSEDED", predecessor_event_id="flow-a", predecessor_revision="v1"),
    ]
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(_with_flows(controlled_source_payload(), flows))
    assert error.value.code == "FLOW_LIFECYCLE_CONFLICT"


@pytest.mark.parametrize("basis,field", [("SETTLEMENT_DATE", "settlement_date"), ("PAYMENT_DATE", "payment_date")])
def test_elected_settlement_or_payment_date_requires_original_source_date_evidence(basis, field):
    payload = _with_flows(controlled_source_payload(), [_flow(source_date="2025-06-29")])
    payload["policy"]["date_basis"] = basis
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(deepcopy(payload))
    assert error.value.code == "FLOW_DATE_POLICY_UNAVAILABLE"
    payload["flows"][0][field] = "2025-07-01"
    result = _admit(payload)
    assert result.portfolio_cash_flows[0].economic_date == date(2025, 7, 1)
    assert result.source_bundle.flows[0].source_date == date(2025, 6, 29)


def test_empty_economic_content_remains_explicit_admitted_zero_not_invented_missing_data():
    payload = controlled_source_payload()
    for row in payload["valuations"]:
        row["amount"] = "0"
    result = _admit(payload)
    assert result.opening_value == result.terminal_value == 0
    assert all(row.amount == 0 for row in result.investor_cash_flows)
    assert all(row.explicitly_empty for row in result.source_bundle.flow_coverage)


@pytest.mark.parametrize("conflict", ["duplicate-pin", "missing-original-body"])
def test_source_vector_cannot_duplicate_identity_or_omit_retained_body(conflict):
    payload = controlled_source_payload()
    if conflict == "duplicate-pin":
        payload["source_pins"].append(deepcopy(payload["source_pins"][0]))
    else:
        del payload["raw_source_bodies"]["money"]
    with pytest.raises(PooledSourceAdmissionError) as error:
        require_source_bindings(
            controlled_request(), PooledSourceBundle.model_validate(payload), tenant_id="controlled-tenant"
        )
    assert error.value.code == (
        "SOURCE_IDENTITY_UNAVAILABLE" if conflict == "duplicate-pin" else "SOURCE_CUT_UNAVAILABLE"
    )


@pytest.mark.parametrize(
    "collection,index,field,value,code",
    [
        ("membership", 1, "source_row_id", "member-a-membership", "MEMBERSHIP_IDENTITY_CONFLICT"),
        ("membership", 0, "effective_to", "2024-12-31", "MEMBERSHIP_IDENTITY_CONFLICT"),
        ("flow_coverage", 0, "portfolio_id", "unselected-member", "MISSING_FLOW_COVERAGE"),
        ("flow_coverage", 0, "source_pin_id", "unretained-pin", "MISSING_FLOW_COVERAGE"),
        ("flow_coverage", 0, "active_event_ids", ["unretained-event"], "MISSING_FLOW_COVERAGE"),
        ("valuations", 0, "portfolio_id", "unselected-member", "SOURCE_IDENTITY_UNAVAILABLE"),
        ("valuations", 0, "source_pin_id", "unretained-pin", "SOURCE_IDENTITY_UNAVAILABLE"),
    ],
)
def test_source_identity_and_population_controls_refuse_unbound_economics(collection, index, field, value, code):
    payload = controlled_source_payload()
    payload[collection][index][field] = value
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == code


def test_boundary_values_cannot_duplicate_even_identical_source_economics():
    payload = controlled_source_payload()
    payload["valuations"].append(deepcopy(payload["valuations"][0]))
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == "BOUNDARY_VALUATION_CONFLICT"


def test_one_namespace_cannot_change_between_portfolio_and_source_event_identity():
    payload = _with_flows(controlled_source_payload(), [_flow(), _flow(member="member-b", identity_scope="SOURCE")])
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == "SOURCE_IDENTITY_CONFLICT"


def test_flow_population_cannot_use_another_pin_than_its_coverage_control():
    payload = _with_flows(controlled_source_payload(), [_flow(source_pin_id="population")])
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == "SOURCE_CUT_CONFLICT"


def test_transfer_pair_is_not_eliminated_without_elected_consolidation_policy():
    payload = _transfer_payload()
    payload["policy"]["transfer_policy"] = "NO_INTERNAL_TRANSFERS"
    with pytest.raises(PooledSourceAdmissionError) as error:
        _admit(payload)
    assert error.value.code == "TRANSFER_POLICY_UNAVAILABLE"


def test_adjacent_included_history_does_not_invent_entry_or_exit_capital():
    payload = controlled_source_payload()
    original = payload["membership"].pop(0)
    payload["membership"].extend(
        [
            {**original, "effective_to": "2025-06-30", "source_row_id": "member-a-first-decision"},
            {**original, "effective_from": "2025-07-01", "source_row_id": "member-a-next-decision"},
        ]
    )
    result = _admit(payload)
    assert (result.opening_value, result.terminal_value) == (Decimal(100), Decimal(110))
    assert not result.portfolio_cash_flows
    assert result.per_member_controls["member-a"]["entry_capital"] == "0"
    assert result.per_member_controls["member-a"]["exit_capital"] == "0"
    assert len(result.source_bundle.membership) == 3
