from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.composites import CompositeMemberReturnFact
from engine.composites import (
    _blocked_composite_period_result,
    _blocked_composite_period_result_for_invalid_ready_facts,
    _build_composite_period_fact_set,
    _build_ready_composite_period_result,
    _build_ready_member_contributions,
    _classify_composite_period_facts,
    _composite_period_fact_metadata,
    calculate_asset_weighted_composite_twr,
)


@dataclass(frozen=True)
class StructuralCompositeMemberReturnFact:
    composite_id: str
    portfolio_id: str
    period_start: date
    period_end: date
    return_value: Decimal
    return_view: str
    beginning_market_value: Decimal
    ending_market_value: Decimal
    reporting_currency: str
    calculation_id: str
    source_snapshot_id: str
    source_fingerprint: str
    restatement_version: str
    status: str
    reason_codes: list[str]


def _fact(
    *,
    portfolio_id: str,
    period_start: str = "2026-01-01",
    period_end: str = "2026-01-31",
    return_value: str = "0.0100",
    beginning_market_value: str = "100.00",
    ending_market_value: str = "101.00",
    reporting_currency: str = "USD",
    return_view: str = "NET_ACTUAL",
    source_fingerprint: str | None = None,
    status: str = "READY",
    reason_codes: list[str] | None = None,
) -> CompositeMemberReturnFact:
    return CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": portfolio_id,
            "period_start": period_start,
            "period_end": period_end,
            "return_value": return_value,
            "return_view": return_view,
            "beginning_market_value": beginning_market_value,
            "ending_market_value": ending_market_value,
            "reporting_currency": reporting_currency,
            "calculation_id": f"calc-{portfolio_id}-{period_end}",
            "source_snapshot_id": f"snapshot-{portfolio_id}-{period_end}",
            "source_fingerprint": source_fingerprint or f"sha256:{portfolio_id}-{period_end}",
            "status": status,
            "reason_codes": reason_codes or [],
        }
    )


def test_blocked_composite_period_result_quantizes_assets_and_preserves_metadata():
    ready_facts = [
        _fact(
            portfolio_id="P1",
            beginning_market_value="0.0000004",
            ending_market_value="10.1234567",
        )
    ]
    excluded_facts = [_fact(portfolio_id="P2", status="BLOCKED", reason_codes=["missing_final_valuation"])]

    result = _blocked_composite_period_result(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        beginning_assets=Decimal("0.0000004"),
        ending_assets=Decimal("10.1234567"),
        ready_facts=ready_facts,
        excluded_facts=excluded_facts,
        return_view="NET_ACTUAL",
        reporting_currency="USD",
        source_fingerprints=["sha256:P1-2026-01-31"],
        restatement_versions=["v1"],
        reason_codes=["nonpositive_composite_beginning_assets"],
    )

    assert result.status == "BLOCKED"
    assert result.return_value is None
    assert str(result.beginning_market_value) == "0.000000"
    assert str(result.ending_market_value) == "10.123457"
    assert result.member_count == 1
    assert result.excluded_member_count == 1
    assert result.return_view == "NET_ACTUAL"
    assert result.reporting_currency == "USD"
    assert result.source_fingerprints == ["sha256:P1-2026-01-31"]
    assert result.restatement_versions == ["v1"]
    assert result.reason_codes == ["nonpositive_composite_beginning_assets"]
    assert result.member_contributions == []


def test_blocked_composite_period_result_defaults_empty_metadata_lists():
    result = _blocked_composite_period_result(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        beginning_assets=Decimal("0"),
        ending_assets=Decimal("0"),
        ready_facts=[],
        excluded_facts=[_fact(portfolio_id="P1", status="BLOCKED", reason_codes=["upstream_twr_blocked"])],
        reason_codes=["no_ready_member_return_facts"],
    )

    assert result.member_count == 0
    assert result.excluded_member_count == 1
    assert result.source_fingerprints == []
    assert result.restatement_versions == []
    assert result.reason_codes == ["no_ready_member_return_facts"]


def test_build_ready_member_contributions_sorts_and_quantizes_member_rows():
    weighted_return, member_contributions = _build_ready_member_contributions(
        ready_facts=[
            _fact(portfolio_id="P2", return_value="0.0300", beginning_market_value="300.00"),
            _fact(portfolio_id="P1", return_value="0.0100", beginning_market_value="100.00"),
        ],
        beginning_assets=Decimal("400.00"),
    )

    assert str(weighted_return) == "0.025000"
    assert [item.portfolio_id for item in member_contributions] == ["P1", "P2"]
    assert [str(item.weight) for item in member_contributions] == [
        "0.250000000000",
        "0.750000000000",
    ]
    assert [str(item.contribution) for item in member_contributions] == [
        "0.002500000000",
        "0.022500000000",
    ]
    assert member_contributions[0].source_snapshot_id == "snapshot-P1-2026-01-31"
    assert member_contributions[1].calculation_id == "calc-P2-2026-01-31"


def test_build_ready_member_contributions_handles_empty_ready_facts():
    weighted_return, member_contributions = _build_ready_member_contributions(
        ready_facts=[],
        beginning_assets=Decimal("400.00"),
    )

    assert weighted_return == Decimal("0")
    assert member_contributions == []


def test_build_composite_period_fact_set_classifies_ready_and_excluded_metadata():
    period_fact_set = _build_composite_period_fact_set(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        facts=[
            _fact(portfolio_id="P2", return_value="0.0200", beginning_market_value="200.00"),
            _fact(portfolio_id="P1", return_value="0.0100", beginning_market_value="100.00"),
            _fact(
                portfolio_id="P3",
                status="BLOCKED",
                reason_codes=["missing_final_valuation", "upstream_twr_blocked"],
            ),
        ],
    )

    assert [fact.portfolio_id for fact in period_fact_set.ready_facts] == ["P2", "P1"]
    assert [fact.portfolio_id for fact in period_fact_set.excluded_facts] == ["P3"]
    assert period_fact_set.reason_codes == ["missing_final_valuation", "upstream_twr_blocked"]
    assert period_fact_set.beginning_assets == Decimal("300.00")
    assert period_fact_set.ending_assets == Decimal("202.00")
    assert period_fact_set.ready_return_views == ["NET_ACTUAL"]
    assert period_fact_set.ready_reporting_currencies == ["USD"]
    assert period_fact_set.ready_source_fingerprints == [
        "sha256:P1-2026-01-31",
        "sha256:P2-2026-01-31",
    ]
    assert period_fact_set.ready_restatement_versions == ["v1"]


def test_composite_period_fact_helpers_classify_and_aggregate_metadata():
    facts = [
        _fact(portfolio_id="P2", return_value="0.0200", beginning_market_value="200.00"),
        _fact(
            portfolio_id="P1",
            return_value="0.0100",
            beginning_market_value="100.00",
            source_fingerprint="sha256:P1-custom",
        ),
        _fact(
            portfolio_id="P3",
            status="BLOCKED",
            reason_codes=["upstream_twr_blocked", "missing_final_valuation"],
        ),
    ]

    ready_facts, excluded_facts = _classify_composite_period_facts(facts)
    metadata = _composite_period_fact_metadata(
        ready_facts=ready_facts,
        excluded_facts=excluded_facts,
    )

    assert [fact.portfolio_id for fact in ready_facts] == ["P2", "P1"]
    assert [fact.portfolio_id for fact in excluded_facts] == ["P3"]
    assert metadata.reason_codes == ["missing_final_valuation", "upstream_twr_blocked"]
    assert metadata.beginning_assets == Decimal("300.00")
    assert metadata.ending_assets == Decimal("202.00")
    assert metadata.ready_return_views == ["NET_ACTUAL"]
    assert metadata.ready_reporting_currencies == ["USD"]
    assert metadata.ready_source_fingerprints == ["sha256:P1-custom", "sha256:P2-2026-01-31"]
    assert metadata.ready_restatement_versions == ["v1"]


def test_composite_period_fact_metadata_deduplicates_sorted_values():
    metadata = _composite_period_fact_metadata(
        ready_facts=[
            _fact(portfolio_id="P2", reporting_currency="SGD", return_view="NET_ACTUAL", source_fingerprint="sha256:z"),
            _fact(portfolio_id="P1", reporting_currency="USD", return_view="GROSS", source_fingerprint="sha256:a"),
            _fact(portfolio_id="P3", reporting_currency="USD", return_view="GROSS", source_fingerprint="sha256:a"),
        ],
        excluded_facts=[
            _fact(portfolio_id="P4", status="BLOCKED", reason_codes=["z_reason", "a_reason"]),
            _fact(portfolio_id="P5", status="BLOCKED", reason_codes=["a_reason"]),
        ],
    )

    assert metadata.reason_codes == ["a_reason", "z_reason"]
    assert metadata.ready_return_views == ["GROSS", "NET_ACTUAL"]
    assert metadata.ready_reporting_currencies == ["SGD", "USD"]
    assert metadata.ready_source_fingerprints == ["sha256:a", "sha256:z"]


def test_build_ready_composite_period_result_quantizes_and_links_growth():
    period_fact_set = _build_composite_period_fact_set(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        facts=[
            _fact(portfolio_id="P1", return_value="0.0100", beginning_market_value="100.00"),
            _fact(portfolio_id="P2", return_value="0.0300", beginning_market_value="300.00"),
        ],
    )

    period_result, next_cumulative_growth = _build_ready_composite_period_result(
        period_fact_set=period_fact_set,
        cumulative_growth=Decimal("1.02"),
    )

    assert next_cumulative_growth == Decimal("1.04550000")
    assert period_result.status == "READY"
    assert str(period_result.return_value) == "0.025000000000"
    assert str(period_result.cumulative_return) == "0.045500000000"
    assert str(period_result.beginning_market_value) == "400.000000"
    assert period_result.member_count == 2
    assert period_result.excluded_member_count == 0
    assert [item.portfolio_id for item in period_result.member_contributions] == ["P1", "P2"]


def test_blocked_composite_period_result_for_invalid_ready_facts_blocks_empty_ready_set():
    result = _blocked_composite_period_result_for_invalid_ready_facts(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        beginning_assets=Decimal("0"),
        ending_assets=Decimal("0"),
        ready_facts=[],
        excluded_facts=[_fact(portfolio_id="P1", status="BLOCKED", reason_codes=["upstream_twr_blocked"])],
        reason_codes=["upstream_twr_blocked"],
        ready_return_views=[],
        ready_reporting_currencies=[],
        ready_source_fingerprints=[],
        ready_restatement_versions=[],
    )

    assert result is not None
    period_result, aggregate_reason_code = result
    assert aggregate_reason_code == "no_ready_member_return_facts"
    assert period_result.reason_codes == ["upstream_twr_blocked"]
    assert period_result.member_count == 0
    assert period_result.excluded_member_count == 1


def test_blocked_composite_period_result_for_invalid_ready_facts_prioritizes_empty_ready_set():
    result = _blocked_composite_period_result_for_invalid_ready_facts(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        beginning_assets=Decimal("0"),
        ending_assets=Decimal("0"),
        ready_facts=[],
        excluded_facts=[],
        reason_codes=[],
        ready_return_views=["GROSS", "NET_ACTUAL"],
        ready_reporting_currencies=["SGD", "USD"],
        ready_source_fingerprints=[],
        ready_restatement_versions=[],
    )

    assert result is not None
    period_result, aggregate_reason_code = result
    assert aggregate_reason_code == "no_ready_member_return_facts"
    assert period_result.reason_codes == ["no_ready_member_return_facts"]
    assert period_result.return_view is None
    assert period_result.reporting_currency is None


def test_blocked_composite_period_result_for_invalid_ready_facts_blocks_nonpositive_assets():
    ready_facts = [_fact(portfolio_id="P1", beginning_market_value="0.00", ending_market_value="10.00")]

    result = _blocked_composite_period_result_for_invalid_ready_facts(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        beginning_assets=Decimal("0"),
        ending_assets=Decimal("10.00"),
        ready_facts=ready_facts,
        excluded_facts=[],
        reason_codes=[],
        ready_return_views=["NET_ACTUAL"],
        ready_reporting_currencies=["USD"],
        ready_source_fingerprints=["sha256:P1-2026-01-31"],
        ready_restatement_versions=["v1"],
    )

    assert result is not None
    period_result, aggregate_reason_code = result
    assert aggregate_reason_code == "nonpositive_composite_beginning_assets"
    assert period_result.return_view == "NET_ACTUAL"
    assert period_result.reporting_currency == "USD"
    assert period_result.source_fingerprints == ["sha256:P1-2026-01-31"]
    assert period_result.reason_codes == ["nonpositive_composite_beginning_assets"]


def test_blocked_composite_period_result_for_invalid_ready_facts_preserves_prior_reason_codes():
    ready_facts = [_fact(portfolio_id="P1", beginning_market_value="0.00", ending_market_value="10.00")]

    result = _blocked_composite_period_result_for_invalid_ready_facts(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        beginning_assets=Decimal("0"),
        ending_assets=Decimal("10.00"),
        ready_facts=ready_facts,
        excluded_facts=[],
        reason_codes=["upstream_member_fact_warning"],
        ready_return_views=["NET_ACTUAL"],
        ready_reporting_currencies=["USD"],
        ready_source_fingerprints=["sha256:P1-2026-01-31"],
        ready_restatement_versions=["v1"],
    )

    assert result is not None
    period_result, aggregate_reason_code = result
    assert aggregate_reason_code == "nonpositive_composite_beginning_assets"
    assert period_result.reason_codes == [
        "upstream_member_fact_warning",
        "nonpositive_composite_beginning_assets",
    ]


def test_blocked_composite_period_result_for_invalid_ready_facts_blocks_mixed_return_views():
    ready_facts = [
        _fact(portfolio_id="P1", return_view="GROSS"),
        _fact(portfolio_id="P2", return_view="NET_ACTUAL"),
    ]

    result = _blocked_composite_period_result_for_invalid_ready_facts(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        beginning_assets=Decimal("200.00"),
        ending_assets=Decimal("202.00"),
        ready_facts=ready_facts,
        excluded_facts=[],
        reason_codes=[],
        ready_return_views=["GROSS", "NET_ACTUAL"],
        ready_reporting_currencies=["USD"],
        ready_source_fingerprints=["sha256:P1-2026-01-31", "sha256:P2-2026-01-31"],
        ready_restatement_versions=["v1"],
    )

    assert result is not None
    period_result, aggregate_reason_code = result
    assert aggregate_reason_code == "mixed_member_return_views"
    assert period_result.return_view is None
    assert period_result.reporting_currency == "USD"
    assert period_result.reason_codes == ["mixed_member_return_views"]


def test_blocked_composite_period_result_for_invalid_ready_facts_blocks_mixed_reporting_currencies():
    ready_facts = [
        _fact(portfolio_id="P1", reporting_currency="USD"),
        _fact(portfolio_id="P2", reporting_currency="SGD"),
    ]

    result = _blocked_composite_period_result_for_invalid_ready_facts(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        beginning_assets=Decimal("200.00"),
        ending_assets=Decimal("202.00"),
        ready_facts=ready_facts,
        excluded_facts=[],
        reason_codes=[],
        ready_return_views=["NET_ACTUAL"],
        ready_reporting_currencies=["SGD", "USD"],
        ready_source_fingerprints=["sha256:P1-2026-01-31", "sha256:P2-2026-01-31"],
        ready_restatement_versions=["v1"],
    )

    assert result is not None
    period_result, aggregate_reason_code = result
    assert aggregate_reason_code == "mixed_member_reporting_currencies"
    assert period_result.return_view == "NET_ACTUAL"
    assert period_result.reporting_currency is None
    assert period_result.reason_codes == ["mixed_member_reporting_currencies"]


def test_blocked_composite_period_result_for_invalid_ready_facts_returns_none_for_ready_period():
    ready_facts = [
        _fact(portfolio_id="P1", reporting_currency="USD"),
        _fact(portfolio_id="P2", reporting_currency="USD"),
    ]

    result = _blocked_composite_period_result_for_invalid_ready_facts(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        beginning_assets=Decimal("200.00"),
        ending_assets=Decimal("202.00"),
        ready_facts=ready_facts,
        excluded_facts=[],
        reason_codes=[],
        ready_return_views=["NET_ACTUAL"],
        ready_reporting_currencies=["USD"],
        ready_source_fingerprints=["sha256:P1-2026-01-31", "sha256:P2-2026-01-31"],
        ready_restatement_versions=["v1"],
    )

    assert result is None


def test_asset_weighted_composite_twr_weights_member_returns_and_links_periods():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            _fact(portfolio_id="P1", return_value="0.0100", beginning_market_value="100.00"),
            _fact(portfolio_id="P2", return_value="0.0300", beginning_market_value="300.00"),
            _fact(
                portfolio_id="P1",
                period_start="2026-02-01",
                period_end="2026-02-28",
                return_value="0.0200",
                beginning_market_value="200.00",
            ),
            _fact(
                portfolio_id="P2",
                period_start="2026-02-01",
                period_end="2026-02-28",
                return_value="-0.0100",
                beginning_market_value="200.00",
            ),
        ],
    )

    assert result.status == "READY"
    assert [str(period.return_value) for period in result.period_results] == [
        "0.025000000000",
        "0.005000000000",
    ]
    assert str(result.cumulative_return) == "0.030125000000"
    assert [str(item.weight) for item in result.period_results[0].member_contributions] == [
        "0.250000000000",
        "0.750000000000",
    ]
    assert result.period_results[0].return_view == "NET_ACTUAL"
    assert result.period_results[0].reporting_currency == "USD"
    assert result.period_results[0].source_fingerprints == ["sha256:P1-2026-01-31", "sha256:P2-2026-01-31"]
    assert result.period_results[0].restatement_versions == ["v1"]


def test_asset_weighted_composite_twr_degrades_when_some_member_facts_are_not_ready():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            _fact(portfolio_id="P1", return_value="0.0100", beginning_market_value="100.00"),
            _fact(
                portfolio_id="P2",
                status="DEGRADED",
                reason_codes=["missing_final_valuation"],
            ),
        ],
    )

    assert result.status == "DEGRADED"
    assert result.period_results[0].status == "DEGRADED"
    assert result.period_results[0].excluded_member_count == 1
    assert result.reason_codes == ["missing_final_valuation"]


def test_asset_weighted_composite_twr_blocks_period_with_no_ready_member_facts():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            _fact(portfolio_id="P1", status="BLOCKED", reason_codes=["upstream_twr_blocked"]),
        ],
    )

    assert result.status == "BLOCKED"
    assert result.cumulative_return is None
    assert result.period_results[0].return_value is None
    assert result.period_results[0].reason_codes == ["upstream_twr_blocked"]


def test_asset_weighted_composite_twr_blocks_nonpositive_beginning_assets():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            _fact(portfolio_id="P1", beginning_market_value="0.00", ending_market_value="10.00"),
        ],
    )

    assert result.status == "BLOCKED"
    assert result.period_results[0].reason_codes == ["nonpositive_composite_beginning_assets"]


def test_asset_weighted_composite_twr_blocks_mixed_return_views():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            _fact(portfolio_id="P1", return_view="GROSS"),
            _fact(portfolio_id="P2", return_view="NET_ACTUAL"),
        ],
    )

    assert result.status == "BLOCKED"
    assert result.period_results[0].return_value is None
    assert result.period_results[0].reason_codes == ["mixed_member_return_views"]


def test_asset_weighted_composite_twr_blocks_mixed_reporting_currencies():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            _fact(portfolio_id="P1", reporting_currency="USD"),
            _fact(portfolio_id="P2", reporting_currency="SGD"),
        ],
    )

    assert result.status == "BLOCKED"
    assert result.period_results[0].return_value is None
    assert result.period_results[0].reason_codes == ["mixed_member_reporting_currencies"]


def test_asset_weighted_composite_twr_returns_no_member_fact_status_without_zero_return():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[],
    )

    assert result.status == "BLOCKED"
    assert result.cumulative_return is None
    assert result.period_results == []
    assert result.reason_codes == ["no_member_return_facts"]


def test_asset_weighted_composite_twr_single_member_matches_member_return_without_dispersion():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            _fact(portfolio_id="P1", return_value="0.0175", beginning_market_value="2500000.00"),
        ],
    )

    assert result.status == "READY"
    assert str(result.cumulative_return) == "0.017500000000"
    assert str(result.period_results[0].return_value) == "0.017500000000"
    assert result.period_results[0].dispersion_equal_weight is None
    assert str(result.period_results[0].member_contributions[0].weight) == "1.000000000000"
    assert str(result.period_results[0].member_contributions[0].contribution) == "0.017500000000"


def test_asset_weighted_composite_twr_member_weights_and_contributions_reconcile():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            _fact(portfolio_id="P1", return_value="0.0100", beginning_market_value="100.00"),
            _fact(portfolio_id="P2", return_value="0.0200", beginning_market_value="200.00"),
            _fact(portfolio_id="P3", return_value="-0.0050", beginning_market_value="700.00"),
        ],
    )

    period = result.period_results[0]
    weights = [item.weight for item in period.member_contributions]
    contributions = [item.contribution for item in period.member_contributions]

    assert str(sum(weights)) == "1.000000000000"
    assert str(sum(contributions)) == str(period.return_value)
    assert str(period.return_value) == "0.001500000000"


def test_asset_weighted_composite_twr_blocks_inactive_gap_without_erasing_later_history():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            _fact(
                portfolio_id="P1",
                period_start="2026-01-01",
                period_end="2026-01-31",
                status="BLOCKED",
                reason_codes=["no_eligible_members_after_membership_policy"],
            ),
            _fact(
                portfolio_id="P1",
                period_start="2026-02-01",
                period_end="2026-02-28",
                return_value="0.0125",
                beginning_market_value="100.00",
            ),
        ],
    )

    assert result.status == "DEGRADED"
    assert result.reason_codes == [
        "no_eligible_members_after_membership_policy",
        "no_ready_member_return_facts",
    ]
    assert result.period_results[0].status == "BLOCKED"
    assert result.period_results[0].return_value is None
    assert result.period_results[1].status == "READY"
    assert str(result.period_results[1].cumulative_return) == "0.012500000000"
    assert str(result.cumulative_return) == "0.012500000000"


def test_asset_weighted_composite_twr_accepts_structural_member_facts():
    result = calculate_asset_weighted_composite_twr(
        composite_id="PB_GLOBAL_BALANCED_USD",
        member_return_facts=[
            StructuralCompositeMemberReturnFact(
                composite_id="PB_GLOBAL_BALANCED_USD",
                portfolio_id="P1",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                return_value=Decimal("0.0100"),
                return_view="NET_ACTUAL",
                beginning_market_value=Decimal("100.00"),
                ending_market_value=Decimal("101.00"),
                reporting_currency="USD",
                calculation_id="calc-P1-2026-01-31",
                source_snapshot_id="snapshot-P1-2026-01-31",
                source_fingerprint="sha256:P1-2026-01-31",
                restatement_version="v1",
                status="READY",
                reason_codes=[],
            )
        ],
    )

    assert result.status == "READY"
    assert str(result.cumulative_return) == "0.010000000000"
