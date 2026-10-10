"""Full-cell arithmetic, complete-universe and observed-number refusal controls."""

import copy
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.adapters.composite_attribution_deployment import UnavailableAttributionAuthority, UnavailableAttributionSource
from app.models.composite_attribution import AttributionGroup, AttributionMemberGroup
from app.ports.composite_attribution import AttributionAdmissionError
from app.services.composite_attribution.admission import admit_attribution
from app.services.composite_attribution.kernel_adapter import calculate_attribution
from tests.composite_attribution_helpers import seal


def admitted(case):
    request, bundle, approval, original, vector = case
    return admit_attribution(request, bundle, approval, tenant_id="tenant-a", original=original, vector=vector)


def test_original_or17_every_effect_and_decimal_unit(financial_case):
    before = copy.deepcopy(financial_case[1].model_dump(mode="json"))
    observation = admitted(financial_case)
    result = calculate_attribution(financial_case[0], observation)
    for row, expected in zip(
        result.groups, ((0.0025, 0.01, 0.002, 0.0145), (0.0025, -0.005, 0.001, -0.0015)), strict=True
    ):
        assert (row.allocation, row.selection, row.interaction, row.total) == pytest.approx(expected, abs=1e-12)
    assert (result.portfolio_return, result.benchmark_return, result.active_return) == pytest.approx(
        (0.068, 0.055, 0.013), abs=1e-12
    )
    assert (result.allocation, result.selection, result.interaction) == pytest.approx((0.005, 0.005, 0.003), abs=1e-12)
    assert result.units == "DECIMAL_RETURN" and result.precision_mode == "FLOAT64"
    assert result.active_return_convention == "ARITHMETIC_DIFFERENCE"
    assert abs(result.reconciliation_delta) < 1e-12
    assert financial_case[1].model_dump(mode="json") == before


@pytest.mark.parametrize("field", ["portfolio_weight", "benchmark_weight", "portfolio_return", "benchmark_return"])
@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True])
def test_missing_nonfinite_and_boolean_are_not_observed_zero(field, value, financial_case):
    payload = financial_case[1].groups[0].model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        AttributionGroup.model_validate(payload)
    payload.pop(field)
    with pytest.raises(ValidationError):
        AttributionGroup.model_validate(payload)


@pytest.mark.parametrize("field", ["portfolio_weight", "benchmark_weight"])
@pytest.mark.parametrize("value", [0, -0.1])
def test_unsupported_weight_conventions_refuse(field, value, financial_case):
    request, bundle, _, original, vector = financial_case
    groups = (bundle.groups[0].model_copy(update={field: value}), bundle.groups[1])
    bundle, approval = seal(bundle.model_copy(update={"groups": groups}))
    with pytest.raises(AttributionAdmissionError):
        admit_attribution(request, bundle, approval, tenant_id="tenant-a", original=original, vector=vector)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-group",
        "hidden-benchmark",
        "page-gap",
        "omission",
        "wire-conflict",
        "wrong-tenant",
        "derivative",
        "maker-checker",
        "missing-member",
        "unknown-member-group",
    ],
)
def test_complete_source_admission_refusals(mutation, financial_case):
    request, bundle, approval, original, vector = financial_case
    changes = {
        "missing-group": {"groups": bundle.groups[:1]},
        "hidden-benchmark": {"expected_benchmark_group_ids": ("g1", "g2", "hidden")},
        "page-gap": {
            "source_pins": (
                bundle.source_pins[0].model_copy(update={"expected_page_count": 2}),
                *bundle.source_pins[1:],
            )
        },
        "omission": {
            "source_pins": (
                bundle.source_pins[0].model_copy(update={"omitted_component_count": 1}),
                *bundle.source_pins[1:],
            )
        },
        "wrong-tenant": {"tenant_id": "tenant-b"},
        "derivative": {"derivatives_present": True},
        "missing-member": {"members": ()},
        "unknown-member-group": {
            "member_groups": (
                bundle.member_groups[0].model_copy(update={"portfolio_id": "unknown"}),
                bundle.member_groups[1],
            )
        },
    }
    if mutation in changes:
        bundle, approval = seal(bundle.model_copy(update=changes[mutation]))
    elif mutation == "wire-conflict":
        bundle = bundle.model_copy(update={"raw_source_bodies": {}})
    elif mutation == "maker-checker":
        approval = approval.model_copy(update={"canonical_checker": approval.canonical_maker})
    with pytest.raises(AttributionAdmissionError):
        admit_attribution(request, bundle, approval, tenant_id="tenant-a", original=original, vector=vector)


def test_symmetric_incomplete_weights_refuse_even_if_effects_reconcile(financial_case):
    request, bundle, _, original, vector = financial_case
    groups = tuple(
        row.model_copy(
            update={"portfolio_weight": row.portfolio_weight * 0.9, "benchmark_weight": row.benchmark_weight * 0.9}
        )
        for row in bundle.groups
    )
    bundle, approval = seal(bundle.model_copy(update={"groups": groups}))
    with pytest.raises(AttributionAdmissionError):
        admit_attribution(request, bundle, approval, tenant_id="tenant-a", original=original, vector=vector)


def test_observed_zero_benchmark_return_is_valid(financial_case):
    request, bundle, _, original, vector = financial_case
    groups = (bundle.groups[0].model_copy(update={"benchmark_return": 0.0}), bundle.groups[1])
    bundle, approval = seal(bundle.model_copy(update={"groups": groups}))
    observation = admit_attribution(request, bundle, approval, tenant_id="tenant-a", original=original, vector=vector)
    assert calculate_attribution(request, observation).benchmark_return == pytest.approx(0.015)


@pytest.mark.parametrize("status,value", [("BLOCKED", None), ("DEGRADED", 0.068), ("READY", 0.07)])
def test_original_must_be_ready_and_reconcile(status, value, financial_case):
    financial_case[3].response.periods[0].status = status
    financial_case[3].response.periods[0].return_value = value
    with pytest.raises(AttributionAdmissionError):
        admitted(financial_case)


def test_default_source_and_separate_financial_authority_are_unavailable(financial_case):
    request, bundle, *_ = financial_case
    with pytest.raises(AttributionAdmissionError, match="Historical"):
        UnavailableAttributionSource().read_population_scope(request, tenant_id="tenant-a")
    with pytest.raises(AttributionAdmissionError, match="Independent"):
        UnavailableAttributionAuthority().verify(request, bundle)


@pytest.mark.parametrize(
    "case,expected_code",
    [
        ("policy-binding", "METHOD_POLICY_CONFLICT"),
        ("policy-period", "METHOD_POLICY_UNAVAILABLE"),
        ("qualification", "ATTRIBUTION_PURPOSE_APPROVAL_CONFLICT"),
        ("duplicate-pin", "SOURCE_IDENTITY_CONFLICT"),
        ("missing-pin", "SOURCE_PIN_INCOMPLETE"),
        ("incompatible-cut", "SOURCE_CUT_CONFLICT"),
        ("history-gap", "SOURCE_HISTORY_UNAVAILABLE"),
        ("changed-wire", "SOURCE_WIRE_CONFLICT"),
    ],
)
def test_historical_policy_and_source_identity_refusals(financial_case, case, expected_code):
    from datetime import timedelta

    from app.models.composite_authority import authority_digest

    request, bundle, _, original, vector = financial_case
    changes = {
        "policy-binding": {"policy": bundle.policy.model_copy(update={"binding_id": "different-policy"})},
        "policy-period": {
            "policy": bundle.policy.model_copy(update={"effective_from": request.period_end + timedelta(days=1)})
        },
        "qualification": {"qualification": "OWNER_QUALIFIED_SOURCE"},
        "duplicate-pin": {"source_pins": (*bundle.source_pins, bundle.source_pins[0])},
        "missing-pin": {"source_pins": bundle.source_pins[1:]},
        "incompatible-cut": {"compatible_pin_ids": bundle.compatible_pin_ids[:1]},
        "history-gap": {
            "source_pins": (
                bundle.source_pins[0].model_copy(update={"coverage_to": request.period_start - timedelta(days=1)}),
                *bundle.source_pins[1:],
            )
        },
    }
    bundle, approval = seal(bundle.model_copy(update=changes.get(case, {})))
    if case == "qualification":
        approval = approval.model_copy(update={"qualification": "SYNTHETIC_NON_CERTIFYING"})
    elif case == "changed-wire":
        wire = copy.deepcopy(bundle.raw_source_bodies)
        wire[bundle.membership_pin_id]["projection"]["membership_revision"] = "changed"
        bundle = bundle.model_copy(update={"raw_source_bodies": wire})
        approval = approval.model_copy(update={"bundle_digest": authority_digest(bundle.model_dump(mode="json"))})
    with pytest.raises(AttributionAdmissionError) as failure:
        admit_attribution(request, bundle, approval, tenant_id="tenant-a", original=original, vector=vector)
    assert failure.value.code == expected_code


def test_approved_excluded_member_is_retained_without_economic_weight(financial_case):
    request, bundle, _, original, vector = financial_case
    excluded = bundle.members[0].model_copy(
        update={
            "portfolio_id": "excluded-member",
            "status": "EXCLUDED",
            "composite_weight": 0,
            "actual_return": 0,
            "source_row_id": "excluded-source-row",
        }
    )
    bundle, approval = seal(
        bundle.model_copy(
            update={
                "members": (*bundle.members, excluded),
                "expected_portfolio_ids": (*bundle.expected_portfolio_ids, excluded.portfolio_id),
            }
        )
    )
    observation = admit_attribution(request, bundle, approval, tenant_id="tenant-a", original=original, vector=vector)
    assert observation.source_bundle.members[-1] == excluded
    assert calculate_attribution(request, observation).portfolio_return == pytest.approx(0.068, abs=1e-12)


@pytest.mark.parametrize("change", ["backward-period", "half-official-scope", "self-correction"])
def test_request_requires_explicit_forward_scope_and_new_correction_identity(financial_case, change):
    from datetime import timedelta

    request = financial_case[0]
    payload = request.model_dump()
    if change == "backward-period":
        payload["period_end"] = request.period_start - timedelta(days=1)
    elif change == "half-official-scope":
        payload["official_revision"] = 1
    else:
        payload["correction_of_calculation_id"] = request.calculation_id
    with pytest.raises(ValidationError):
        request.model_validate(payload)


@pytest.mark.parametrize("benchmark_g1,zero_g3", [(".04", False), (".06", False), (".04", True)])
def test_two_included_members_three_groups_against_rational_oracle(financial_case, benchmark_g1, zero_g3):
    """Root's independent pooled control, distinct from the one-member OR17 fixture."""
    request, bundle, original, vector, capital, weights, returns = _two_member_case(
        financial_case, benchmark_g1, zero_g3
    )
    bundle, approval = seal(bundle)
    before = copy.deepcopy(bundle.model_dump(mode="json"))
    result = calculate_attribution(
        request, admit_attribution(request, bundle, approval, tenant_id="tenant-a", original=original, vector=vector)
    )
    wp = [sum(capital[m] * weights[m][g] for m in range(2)) for g in range(3)]
    rp = [sum(capital[m] * weights[m][g] * returns[m][g] for m in range(2)) / wp[g] for g in range(3)]
    wb = list(map(Fraction, (".3", ".2", ".5")))
    rb = list(map(Fraction, (benchmark_g1, "-.02", "0" if zero_g3 else ".015")))
    benchmark = sum(w * r for w, r in zip(wb, rb, strict=True))
    portfolio = sum(w * r for w, r in zip(wp, rp, strict=True))
    expected = {}
    for g, row in enumerate(bundle.groups):
        assert row.portfolio_weight == pytest.approx(float(wp[g]), abs=1e-12)
        assert row.portfolio_return == pytest.approx(float(rp[g]), abs=1e-12)
        effects = ((wp[g] - wb[g]) * (rb[g] - benchmark), wb[g] * (rp[g] - rb[g]), (wp[g] - wb[g]) * (rp[g] - rb[g]))
        expected[row.group_id] = (*effects, sum(effects))
    for row in result.groups:
        assert (row.allocation, row.selection, row.interaction, row.total) == pytest.approx(
            tuple(map(float, expected[row.group_id])), abs=1e-12
        )
    assert (result.portfolio_return, result.benchmark_return, result.active_return) == pytest.approx(
        tuple(map(float, (portfolio, benchmark, portfolio - benchmark))), abs=1e-12
    )
    assert (result.allocation, result.selection, result.interaction) == pytest.approx(
        tuple(float(sum(row[i] for row in expected.values())) for i in range(3)), abs=1e-12
    )
    assert abs(result.reconciliation_delta) <= 1e-12
    assert bundle.model_dump(mode="json") == before
    reversed_bundle, reversed_approval = seal(bundle.model_copy(update={"groups": tuple(reversed(bundle.groups))}))
    reordered = calculate_attribution(
        request,
        admit_attribution(
            request, reversed_bundle, reversed_approval, tenant_id="tenant-a", original=original, vector=vector
        ),
    )
    assert {row.group_id: row for row in result.groups} == {row.group_id: row for row in reordered.groups}
    for field in ("portfolio_return", "benchmark_return", "active_return", "allocation", "selection", "interaction"):
        assert getattr(reordered, field) == pytest.approx(getattr(result, field), abs=1e-12)
    incomplete, incomplete_approval = seal(bundle.model_copy(update={"member_groups": bundle.member_groups[:-1]}))
    with pytest.raises(AttributionAdmissionError) as failure:
        admit_attribution(
            request, incomplete, incomplete_approval, tenant_id="tenant-a", original=original, vector=vector
        )
    assert failure.value.code == "MEMBER_GROUP_UNIVERSE_INCOMPLETE"


def _two_member_case(financial_case, benchmark_g1, zero_g3):
    request, bundle, _, original, vector = financial_case
    capital = list(map(Fraction, (".7", ".3")))
    weights = [list(map(Fraction, row)) for row in ((".2", ".3", ".5"), (".4", ".4", ".2"))]
    returns = [
        list(map(Fraction, row))
        for row in ((".09", "-.03", "0" if zero_g3 else ".04"), (".05", ".02", "0" if zero_g3 else "-.01"))
    ]
    member_returns = list(map(Fraction, (".009", ".028") if zero_g3 else (".029", ".026")))
    ids = ("member-a", "member-b")
    members = tuple(
        bundle.members[0].model_copy(
            update={
                "portfolio_id": identity,
                "composite_weight": float(capital[m]),
                "actual_return": float(member_returns[m]),
                "source_row_id": identity + "-source",
            }
        )
        for m, identity in enumerate(ids)
    )
    member_groups = tuple(
        AttributionMemberGroup(
            portfolio_id=identity,
            group_id=f"g{g + 1}",
            member_weight=float(weights[m][g]),
            actual_return=float(returns[m][g]),
            source_row_id=f"{identity}-g{g + 1}",
        )
        for m, identity in enumerate(ids)
        for g in range(3)
    )
    # Observed pooled source values are fixed independently of the oracle above.
    groups = tuple(
        AttributionGroup(
            group_id=f"g{g + 1}",
            portfolio_weight=float(Fraction(wp)),
            portfolio_return=float(rp),
            benchmark_weight=float(Fraction(wb)),
            benchmark_return=float(Fraction(rb)),
            source_row_id=f"pooled-g{g + 1}",
        )
        for g, (wp, rp, wb, rb) in enumerate(
            (
                (".26", Fraction(93, 1300), ".3", benchmark_g1),
                (".33", Fraction(-13, 1100), ".2", "-.02"),
                (".41", Fraction(0) if zero_g3 else Fraction(67, 2050), ".5", "0" if zero_g3 else ".015"),
            )
        )
    )
    bundle = bundle.model_copy(
        update={
            "members": members,
            "member_groups": member_groups,
            "groups": groups,
            "expected_portfolio_ids": ids,
            "expected_group_ids": ("g1", "g2", "g3"),
            "expected_benchmark_group_ids": ("g1", "g2", "g3"),
        }
    )
    original.response.periods[0].return_value = Decimal(".0147" if zero_g3 else ".0281")
    original.response.periods[0].member_contributions = [
        SimpleNamespace(
            portfolio_id=identity,
            beginning_asset_weight=Decimal(str(float(capital[m]))),
            return_value=Decimal(str(float(member_returns[m]))),
        )
        for m, identity in enumerate(ids)
    ]
    return request, bundle, original, vector, capital, weights, returns
