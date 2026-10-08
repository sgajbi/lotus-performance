"""Independent economic controls for existing engines, not source admission proof."""

from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction

import pandas as pd
import pytest

from app.models.composites import CompositeMemberReturnFact
from core.envelope import FXRequestBlock
from engine.composites import calculate_asset_weighted_composite_twr
from engine.config import EngineConfig, PrecisionMode
from engine.ror import calculate_daily_ror
from engine.schema import PortfolioColumns

DATES = [date(2026, 1, 5), date(2026, 1, 6)]


def _member_returns(*, assets, flows, currency, rates, precision):
    number = Decimal if precision == PrecisionMode.DECIMAL_STRICT else float
    frame = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(DATES),
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime([DATES[0]] * 2),
            PortfolioColumns.BEGIN_MV: [number(row[0]) for row in assets],
            PortfolioColumns.END_MV: [number(row[1]) for row in assets],
            PortfolioColumns.BOD_CF: [number("0")] * 2,
            PortfolioColumns.EOD_CF: [number(value) for value in flows],
            PortfolioColumns.MGMT_FEES: [number("0")] * 2,
        }
    )
    config = EngineConfig(
        performance_start_date=DATES[0],
        report_end_date=DATES[-1],
        metric_basis="GROSS",
        period_type="YTD",
        precision_mode=precision,
        currency_mode="BOTH",
        source_currency=currency,
        report_ccy="USD",
        fx=FXRequestBlock.model_validate(
            {
                "rates": [
                    {"date": fixing_date, "ccy": currency, "rate": rate}
                    for fixing_date, rate in zip(["2026-01-04", "2026-01-05", "2026-01-06"], rates)
                ]
            }
        ),
    )
    calculated = calculate_daily_ror(frame, "GROSS", config)
    return [Decimal(str(value)) / 100 for value in calculated[PortfolioColumns.DAILY_ROR.value]]


def _fact(member, day, value, beginning, ending, *, currency="USD"):
    return CompositeMemberReturnFact(
        composite_id="FX_CONTROL",
        portfolio_id=member,
        period_start=day,
        period_end=day,
        return_value=value,
        return_view="GROSS",
        beginning_market_value=Decimal(beginning),
        ending_market_value=Decimal(ending),
        reporting_currency=currency,
        calculation_id=f"synthetic-{member}-{day}",
        source_snapshot_id=f"synthetic-{member}-{day}",
        source_fingerprint=f"synthetic-{member}-{day}",
        restatement_sequence=1,
        restatement_version="synthetic-1",
    )


def _rational(value):
    return Decimal(value.numerator) / Decimal(value.denominator)


@pytest.mark.parametrize("precision", [PrecisionMode.DECIMAL_STRICT, PrecisionMode.FLOAT64])
def test_two_currency_weighted_composite_links_two_periods_against_rational_controls(precision):
    """Fixtures are explicitly preconverted; materialization must later prove this conversion."""
    with localcontext() as context:
        context.prec = 50
        eur_returns = _member_returns(
            assets=[("100", "102"), ("102", "103")],
            flows=["0", "0"],
            currency="EUR",
            rates=["1.3", "1.4", "1.42"],
            precision=precision,
        )
        usd_returns = _member_returns(
            assets=[("100", "101"), ("101", "102")],
            flows=["0", "0"],
            currency="USD",
            rates=["1", "1", "1"],
            precision=precision,
        )
        member_tolerance = Decimal("1e-45") if precision == PrecisionMode.DECIMAL_STRICT else Decimal("1e-15")
        assert abs(eur_returns[0] - _rational(Fraction(32, 325))) < member_tolerance
        facts = [
            _fact("EUR_MEMBER", DATES[0], eur_returns[0], "130", "142.8"),
            _fact("USD_MEMBER", DATES[0], usd_returns[0], "100", "101"),
            _fact("EUR_MEMBER", DATES[1], eur_returns[1], "142.8", "146.26"),
            _fact("USD_MEMBER", DATES[1], usd_returns[1], "101", "102"),
        ]
        result = calculate_asset_weighted_composite_twr(composite_id="FX_CONTROL", member_return_facts=facts)
        assert result.status == "READY"
        for period, oracle in zip(result.period_results, [Fraction(3, 50), Fraction(223, 12190)]):
            assert abs(period.return_value - _rational(oracle)) <= Decimal("1e-12")
        assert abs(result.cumulative_return - _rational(Fraction(913, 11500))) <= Decimal("1e-12")
        assert result.period_results[0].beginning_market_value == Decimal("230")
        assert result.period_results[-1].ending_market_value == Decimal("248.26")
        # Native equal weights would yield a different economic result even with translated returns.
        wrong_equal_weight_return = sum([eur_returns[0], usd_returns[0]]) / 2
        assert abs(result.period_results[0].return_value - wrong_equal_weight_return) > Decimal("0.005")


def test_economic_date_eod_flow_reconciles_translated_returns_and_converted_money():
    with localcontext() as context:
        context.prec = 50
        actual = _member_returns(
            assets=[("100", "110"), ("110", "112.2")],
            flows=["10", "0"],
            currency="EUR",
            rates=["1.3", "1.35", "1.4"],
            precision=PrecisionMode.DECIMAL_STRICT,
        )
        # Independent money controls: day1 closing148.5, flow13.5, day2 closing157.08 USD.
        controls = [(Decimal("148.5") - Decimal("13.5")) / Decimal("130") - 1, Decimal("157.08") / Decimal("148.5") - 1]
        for calculated, expected in zip(actual, controls):
            assert abs(calculated - expected) < Decimal("1e-45")
        assert abs((1 + actual[0]) * (1 + actual[1]) - 1 - _rational(Fraction(32, 325))) < Decimal("1e-45")
        wrong_day1 = (Decimal("148.5") - Decimal("14")) / Decimal("130") - 1
        assert abs(actual[0] - wrong_day1) > Decimal("0.003")


def test_composite_keeps_refusing_unconverted_mixed_currency_assets():
    facts = [
        _fact("EUR_MEMBER", DATES[0], Decimal("0.02"), "100", "102", currency="EUR"),
        _fact("USD_MEMBER", DATES[0], Decimal("0.01"), "100", "101"),
    ]
    result = calculate_asset_weighted_composite_twr(composite_id="FX_CONTROL", member_return_facts=facts)
    assert result.status == "BLOCKED"
    assert result.cumulative_return is None
    assert result.period_results[0].return_value is None
    assert "mixed_member_reporting_currencies" in result.reason_codes
