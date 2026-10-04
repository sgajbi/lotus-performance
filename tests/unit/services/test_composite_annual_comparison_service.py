from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.models.composite_annual_comparison import CompositeAnnualComparisonRequest
from app.services.composite_annual_dispersion.comparison import compare_annual_member_dispersion
from core.errors import APIError
from tests.unit.services.test_composite_annual_dispersion_service import MemoryReader, annual_request, year_records


def candidate_records(**changes):
    """Separate publication chronology while preserving independently admitted source evidence."""
    result = []
    for record in year_records(**changes):
        sequence = record.command.restatement_sequence + 24
        identity = uuid5(NAMESPACE_URL, f"annual-comparison-candidate/{record.command.materialization_id}")
        command = record.command.model_copy(update={"restatement_sequence": sequence, "materialization_id": identity})
        outcomes = [
            item.model_copy(
                update={
                    "fact": item.fact.model_copy(
                        update={"restatement_sequence": sequence, "restatement_version": str(identity)}
                    )
                }
            )
            if item.fact is not None
            else item
            for item in record.outcomes
        ]
        result.append(replace(record, command=command, outcomes=outcomes))
    return result


def pair_request(baseline, candidate):
    return CompositeAnnualComparisonRequest(baseline=annual_request(baseline), candidate=annual_request(candidate))


def independent_sample_output(percentages, *, population=False):
    returns = [Fraction(value, 100) for value in percentages]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) if population else len(returns) - 1)
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        return (Decimal(variance.numerator) / Decimal(variance.denominator)).sqrt().quantize(Decimal("1e-12"))


@pytest.mark.parametrize(
    ("changes", "returns", "added", "removed"),
    [
        ({"count": 7, "excluded": ("6",)}, [1, 2, 3, 4, 5, 7], ["7"], ["6"]),
        ({"count": 5}, [1, 2, 3, 4, 5], [], ["6"]),
    ],
)
def test_independent_exact_oracles_population_reversal_and_reordered_replay(changes, returns, added, removed):
    baseline, candidate = year_records(), candidate_records(**changes)
    reader = MemoryReader(baseline + candidate)
    result = compare_annual_member_dispersion(pair_request(baseline, candidate), tenant_id="tenant-a", reader=reader)
    assert result.baseline.value == independent_sample_output([1, 2, 3, 4, 5, 6]) == Decimal(".018708286934")
    assert result.candidate.value == independent_sample_output(returns)
    assert result.value == independent_sample_output(returns) - independent_sample_output([1, 2, 3, 4, 5, 6])
    assert result.full_year_members_added == added
    assert result.full_year_members_removed == removed
    reverse = compare_annual_member_dispersion(pair_request(candidate, baseline), tenant_id="tenant-a", reader=reader)
    assert reverse.value == -result.value
    assert reverse.full_year_members_added == removed
    assert reverse.full_year_members_removed == added
    replay = compare_annual_member_dispersion(
        pair_request(baseline[::-1], candidate[::-1]), tenant_id="tenant-a", reader=reader
    )
    assert replay == result


def test_different_evidence_can_have_zero_delta_without_causal_claim():
    baseline, candidate = year_records(), year_records(corrected=True)
    result = compare_annual_member_dispersion(
        pair_request(baseline, candidate), tenant_id="tenant-a", reader=MemoryReader(baseline + candidate)
    )
    assert result.value == Decimal(0)
    assert result.status == "AVAILABLE"
    assert result.baseline.result_fingerprint != result.candidate.result_fingerprint
    assert result.baseline.members[0].annual_return != result.candidate.members[0].annual_return


def test_available_zero_dispersion_is_distinct_from_unavailable_population():
    records = year_records(corrected=True, count=7, excluded=("2", "3", "4", "5", "6"))
    result = compare_annual_member_dispersion(
        pair_request(records, records), tenant_id="tenant-a", reader=MemoryReader(records)
    )
    assert result.baseline.full_year_member_count == 2
    assert result.baseline.value == result.candidate.value == result.value == 0
    assert result.status == "AVAILABLE" and result.reason_codes == []


def test_weighted_public_method_uses_independent_equal_asset_population_oracle():
    baseline, candidate = year_records(), candidate_records(count=7, excluded=("6",))
    request = pair_request(baseline, candidate)
    request.baseline.method = request.candidate.method = "YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV"
    result = compare_annual_member_dispersion(request, tenant_id="tenant-a", reader=MemoryReader(baseline + candidate))
    assert result.baseline.value == independent_sample_output([1, 2, 3, 4, 5, 6], population=True)
    assert result.candidate.value == independent_sample_output([1, 2, 3, 4, 5, 7], population=True)
    assert result.value == result.candidate.value - result.baseline.value


@pytest.mark.parametrize("side", ["baseline", "candidate", "both"])
def test_unavailable_outputs_remain_null_with_side_specific_reasons(side):
    baseline = year_records(count=1) if side in {"baseline", "both"} else year_records()
    candidate = candidate_records(count=1) if side in {"candidate", "both"} else candidate_records(count=5)
    result = compare_annual_member_dispersion(
        pair_request(baseline, candidate), tenant_id="tenant-a", reader=MemoryReader(baseline + candidate)
    )
    assert result.value is None and result.status == "UNAVAILABLE"
    assert result.reason_codes == [
        f"{name}_ANNUAL_DISPERSION_INSUFFICIENT_MEMBERS"
        for name in ("BASELINE", "CANDIDATE")
        if side == "both" or name.lower() == side
    ]


@pytest.mark.parametrize("basis", ["definition_label", "policy_version"])
def test_cross_side_basis_guard_accepts_common_basis_and_refuses_different_admitted_basis(basis):
    baseline = year_records()
    candidate = candidate_records(count=5, **{basis: "different"})
    with pytest.raises(APIError) as refused:
        compare_annual_member_dispersion(
            pair_request(baseline, candidate), tenant_id="tenant-a", reader=MemoryReader(baseline + candidate)
        )
    assert refused.value.error_code == "ANNUAL_COMPARISON_POLICY_BASIS_MISMATCH"


def test_comparison_is_independent_of_callers_decimal_context():
    baseline, candidate = year_records(), candidate_records(count=7, excluded=("6",))
    reader = MemoryReader(baseline + candidate)
    with localcontext(Context(prec=2)):
        result = compare_annual_member_dispersion(
            pair_request(baseline, candidate), tenant_id="tenant-a", reader=reader
        )
    assert result.value == Decimal(".002894182061")


def test_tenant_binds_comparison_fingerprint_and_invalid_authority_is_refused():
    results = []
    for tenant in ("tenant-a", "tenant-b"):
        records = year_records(tenant=tenant)
        results.append(
            compare_annual_member_dispersion(
                pair_request(records, records), tenant_id=tenant, reader=MemoryReader(records)
            )
        )
    assert results[0].value == results[1].value == 0
    assert results[0].result_fingerprint != results[1].result_fingerprint
    with pytest.raises(APIError):
        compare_annual_member_dispersion(pair_request(records, records), tenant_id="", reader=MemoryReader(records))
