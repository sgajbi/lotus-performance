from __future__ import annotations

from app.models.composites import CompositeMemberReturnFact
from engine.composites import calculate_asset_weighted_composite_twr


def _fact(
    *,
    portfolio_id: str,
    period_start: str = "2026-01-01",
    period_end: str = "2026-01-31",
    return_value: str = "0.0100",
    beginning_market_value: str = "100.00",
    ending_market_value: str = "101.00",
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
            "beginning_market_value": beginning_market_value,
            "ending_market_value": ending_market_value,
            "reporting_currency": "USD",
            "calculation_id": f"calc-{portfolio_id}-{period_end}",
            "source_snapshot_id": f"snapshot-{portfolio_id}-{period_end}",
            "status": status,
            "reason_codes": reason_codes or [],
        }
    )


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
