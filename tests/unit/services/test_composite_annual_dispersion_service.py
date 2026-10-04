from calendar import monthrange
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.models.composite_annual_dispersion import CompositeAnnualDispersionRequest
from app.models.composite_materialization import CompositeMemberMaterializationOutcome, CompositeMemberSourceEvidence
from app.models.composites import CompositeMemberReturnFact
from app.models.portfolio_asset_evidence import PortfolioSourceAssetEvidence
from app.models.requests import PerformanceRequest
from app.models.twr_requests import TWRResolvedExecutionRequest
from app.services.composite_annual_dispersion.application import calculate_annual_member_dispersion
from app.services.composite_materialization.records import MaterializationRecord
from app.services.composite_materialization.source_contract import source_digest
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIError
from tests.composite_materialization_helpers import admitted, command_for, source_products


def month_record(
    month,
    *,
    count=6,
    excluded=(),
    corrected=False,
    tenant="tenant-a",
    definition_label="Balanced composite",
    policy_version="policy.v1",
):
    start, end = date(2026, month, 1), date(2026, month, monthrange(2026, month)[1])
    products = deepcopy(source_products(tenant_id=tenant))
    definition, membership, attestation = products
    definition["display_name"] = definition_label
    definition["eligibility_policy_version"] = policy_version
    definition["content_hash"] = source_digest(definition)
    membership["policy_version"] = policy_version
    template = membership["decisions"][0]
    identities = [str(i) for i in range(1, count + 1)]
    membership["decisions"] = [
        {
            **template,
            "portfolio_id": identity,
            "status": "EXCLUDED" if identity in excluded else "INCLUDED",
            "reason_code": "POLICY_EXCLUDED" if identity in excluded else None,
            "effective_from": start.isoformat(),
            "effective_to": end.isoformat(),
        }
        for identity in identities
    ]
    membership["membership_revision"] = f"month-{month}-{'corrected' if corrected else 'original'}"
    membership["content_hash"] = source_digest(membership)
    attestation.update(
        policy_version=policy_version,
        membership_revision=membership["membership_revision"],
        membership_content_hash=membership["content_hash"],
        coverage_from=start.isoformat(),
        coverage_to=end.isoformat(),
        expected_portfolio_ids=identities,
        expected_portfolio_count=count,
        observed_portfolio_count=count,
    )
    attestation["content_hash"] = source_digest(attestation)
    command = command_for(
        products,
        materialization_id=uuid5(
            NAMESPACE_URL, f"annual-example/{tenant}/{membership['membership_revision']}/{count}/{excluded}"
        ),
        period_start=start,
        period_end=end,
        member_calculations=[],
        policy_version=policy_version,
        membership_revision=membership["membership_revision"],
        restatement_sequence=month + (12 if corrected else 0),
    )
    prepared = []
    for identity in identities:
        if identity in excluded:
            continue
        calculation_id = uuid5(NAMESPACE_URL, f"annual-example/{tenant}/{membership['membership_revision']}/{identity}")
        ret = Decimal(identity) / 100 if month == 1 else Decimal(0)
        if corrected and identity == "1" and month == 1:
            ret = Decimal(".07")
        request = TWRResolvedExecutionRequest(
            portfolio=PerformanceRequest.model_validate(
                {
                    "calculation_id": calculation_id,
                    "portfolio_id": identity,
                    "performance_start_date": "2026-01-01",
                    "report_start_date": start,
                    "report_end_date": end,
                    "metric_basis": "NET",
                    "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
                    "valuation_points": [
                        {"perf_date": start, "begin_mv": "100", "end_mv": "100"},
                        {"perf_date": end, "begin_mv": "100", "end_mv": str(100 * (1 + ret))},
                    ],
                }
            )
        )
        fingerprint, calculation_hash = generate_value_fingerprint(request, "controlled-annual-v1")
        prepared.append(
            (
                identity,
                ret,
                request,
                {
                    "portfolio_id": identity,
                    "calculation_id": calculation_id,
                    "input_fingerprint": fingerprint,
                    "calculation_hash": calculation_hash,
                },
            )
        )
    command = type(command).model_validate(
        {**command.model_dump(), "member_calculations": [item[3] for item in prepared]}
    )
    source = admitted(command, products, tenant_id=tenant)
    outcomes = []
    for identity in excluded:
        outcomes.append(
            CompositeMemberMaterializationOutcome(
                portfolio_id=identity, state="EXCLUDED", reason_code="POLICY_EXCLUDED", retryable=False
            )
        )
    for identity, ret, request, reference in prepared:
        assets = PortfolioSourceAssetEvidence(
            portfolio_currency="USD",
            observations=[
                {"valuation_date": start, "beginning_market_value": "100", "ending_market_value": "100"},
                {"valuation_date": end, "beginning_market_value": "100", "ending_market_value": str(100 * (1 + ret))},
            ],
        )
        evidence = CompositeMemberSourceEvidence.model_validate(
            {
                "engine_version": "controlled-annual-v1",
                "precision_mode": "FLOAT64",
                "input_fingerprint": reference["input_fingerprint"],
                "calculation_hash": reference["calculation_hash"],
                "calculation_request": request,
                "membership_snapshot_id": command.membership_content_hash,
                "asset_evidence_fingerprint": generate_value_fingerprint(assets, "portfolio-source-assets.v1")[0],
                "period_return": ret,
                "source_assets": assets,
                "core_snapshots": [
                    {
                        "snapshot_id": f"synthetic-{identity}-{month}",
                        "source_identifier": identity,
                        "request_as_of_date": end,
                        "request_fingerprint": "a" * 64,
                        "response_fingerprint": "b" * 64,
                        "retrieved_at_utc": "2027-01-01T00:00:00Z",
                    }
                ],
            }
        )
        fact = CompositeMemberReturnFact(
            composite_id="COMPOSITE",
            portfolio_id=identity,
            period_start=start,
            period_end=end,
            return_value=ret,
            beginning_market_value=100,
            ending_market_value=100 * (1 + ret),
            reporting_currency="USD",
            calculation_id=str(reference["calculation_id"]),
            source_snapshot_id=generate_value_fingerprint(evidence, "composite-member-source.v1")[0],
            source_fingerprint=reference["calculation_hash"],
            restatement_version=str(command.materialization_id),
            restatement_sequence=command.restatement_sequence,
        )
        outcomes.append(
            CompositeMemberMaterializationOutcome(
                portfolio_id=identity,
                state="READY",
                reason_code="MEMBER_FACT_VERIFIED",
                retryable=False,
                fact=fact,
                source_evidence=evidence,
            )
        )
    return MaterializationRecord(command, "operator", source, outcomes, "COMPLETE", None, 2)


def year_records(**changes):
    return [month_record(month, **changes) for month in range(1, 13)]


class MemoryReader:
    def __init__(self, records):
        self.records = {record.command.materialization_id: record for record in records}

    def get(self, materialization_id, *, tenant_id):
        return self.records[materialization_id]


def annual_request(records, **changes):
    return CompositeAnnualDispersionRequest(
        composite_id="COMPOSITE",
        year=2026,
        return_view="NET_ACTUAL",
        reporting_currency="USD",
        materialization_ids=[record.command.materialization_id for record in records],
        **changes,
    )


def test_full_year_member_intersection_matches_or11_and_exact_reordered_replay():
    records = year_records()
    reader = MemoryReader(records)
    request = annual_request(records)
    result = calculate_annual_member_dispersion(request, tenant_id="tenant-a", reader=reader)
    assert result.value == Decimal(".018708286934")
    assert (result.year_end_member_count, result.full_year_member_count) == (6, 6)
    assert [item.annual_return for item in result.members] == [Decimal(i) / 100 for i in range(1, 7)]
    assert result.publication_state == "CALCULATED_ANALYSIS"
    assert result.qualification == "RETAINED_SOURCE_ATTESTATION_NOT_LIVE_QUALIFIED"
    assert result.reporting_applicability == "REQUIRES_PROFILE_REVIEW"
    assert (
        calculate_annual_member_dispersion(annual_request(list(reversed(records))), tenant_id="tenant-a", reader=reader)
        == result
    )


def test_normal_partial_year_membership_changes_population_without_data_failure():
    records = year_records()
    records[5] = month_record(6, excluded=("6",))
    result = calculate_annual_member_dispersion(
        annual_request(records), tenant_id="tenant-a", reader=MemoryReader(records)
    )
    assert result.status == "AVAILABLE"
    assert (result.year_end_member_count, result.full_year_member_count) == (6, 5)
    assert result.value == Decimal(".015811388301")
    assert result.reporting_applicability == "NOT_REQUIRED_SMALL_POPULATION"


@pytest.mark.parametrize("count", [1, 2, 5, 6])
def test_population_computability_and_presentation_thresholds_are_separate(count):
    records = year_records(count=count)
    result = calculate_annual_member_dispersion(
        annual_request(records), tenant_id="tenant-a", reader=MemoryReader(records)
    )
    assert result.full_year_member_count == count
    assert result.year_end_member_count == count
    assert result.reporting_applicability == (
        "NOT_REQUIRED_SMALL_POPULATION" if count <= 5 else "REQUIRES_PROFILE_REVIEW"
    )
    if count == 1:
        assert result.value is None
        assert result.status == "UNAVAILABLE"
        assert result.reason_codes == ["ANNUAL_DISPERSION_INSUFFICIENT_MEMBERS"]
    else:
        assert result.value is not None
        assert result.status == "AVAILABLE"
        assert result.reason_codes == []


@pytest.mark.parametrize(
    "change",
    ["missing_outcome", "unknown_membership", "waiting", "tenant", "period", "fee", "currency", "definition", "policy"],
)
def test_annual_reader_refuses_missing_unknown_or_incompatible_evidence(change):
    records = year_records()
    record = records[2]
    tenant = "tenant-a"
    request = annual_request(records)
    if change == "missing_outcome":
        records[2] = replace(record, outcomes=record.outcomes[:-1])
    elif change == "unknown_membership":
        source = record.source.model_copy(deep=True)
        source.membership.decisions[0].status = "PENDING_REVIEW"
        records[2] = replace(record, source=source)
    elif change == "waiting":
        records[2] = replace(record, state="WAITING")
    elif change == "tenant":
        tenant = "tenant-b"
    elif change == "definition":
        records[2] = month_record(3, definition_label="Revised definition")
    elif change == "policy":
        records[2] = month_record(3, policy_version="policy.v2")
    else:
        field, value = {
            "period": ("period_start", date(2026, 3, 2)),
            "fee": ("return_view", "GROSS"),
            "currency": ("reporting_currency", "EUR"),
        }[change]
        records[2] = replace(record, command=record.command.model_copy(update={field: value}))
    with pytest.raises(APIError) as refused:
        calculate_annual_member_dispersion(request, tenant_id=tenant, reader=MemoryReader(records))
    if change in {"definition", "policy"}:
        assert refused.value.error_code == "ANNUAL_DISPERSION_POLICY_BASIS_MISMATCH"


def test_original_and_corrected_receipt_vectors_remain_independently_replayable():
    original, corrected = year_records(), year_records(corrected=True)
    reader = MemoryReader(original + corrected)
    old = calculate_annual_member_dispersion(annual_request(original), tenant_id="tenant-a", reader=reader)
    new = calculate_annual_member_dispersion(annual_request(corrected), tenant_id="tenant-a", reader=reader)
    assert old.value == Decimal(".018708286934")
    assert new.value == Decimal(".018708286934")  # 2%..7% has the same spread; the version identity still changes.
    assert old.members[0].annual_return == Decimal(".01")
    assert new.members[0].annual_return == Decimal(".07")
    assert old.result_fingerprint != new.result_fingerprint
    assert calculate_annual_member_dispersion(annual_request(original), tenant_id="tenant-a", reader=reader) == old
