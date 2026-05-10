# tests/unit/engine/test_contribution.py
import pandas as pd
import pytest

from app.models.contribution_requests import ContributionRequest, Smoothing
from common.enums import WeightingScheme
from engine.config import EngineConfig, PeriodType, PrecisionMode
from engine.contribution import (
    _calculate_carino_factor_for_return,
    _calculate_carino_factors,
    _calculate_daily_instrument_contributions,
    _carino_smoothing_domain_is_valid,
    _prepare_hierarchical_data,
    build_hierarchical_contribution_result,
    calculate_hierarchical_contribution,
)
from engine.runtime import base_only_engine_config


@pytest.fixture
def hierarchical_request_fixture(happy_path_payload):
    """Provides a valid hierarchical request object for testing."""
    payload = happy_path_payload.copy()
    payload["hierarchy"] = ["sector", "region"]
    payload["positions_data"].append(
        {
            "position_id": "Stock_B",
            "meta": {"sector": "Healthcare", "region": "US"},
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408},
                {"perf_date": "2025-01-02", "begin_mv": 408, "end_mv": 410},
            ],
        }
    )
    payload["positions_data"][0]["meta"]["region"] = "US"
    # Remove legacy field to use the one from the fixture
    payload.pop("period_type", None)
    return ContributionRequest.model_validate(payload)


@pytest.fixture
def prepared_data_fixture(hierarchical_request_fixture):
    """Provides the output of the data preparation step for use in other tests."""
    return _prepare_hierarchical_data(hierarchical_request_fixture)


def test_prepare_hierarchical_data(hierarchical_request_fixture):
    """Tests that TWR runs and combines position results with metadata."""
    instruments_df, portfolio_df = _prepare_hierarchical_data(hierarchical_request_fixture)

    assert not instruments_df.empty
    assert not portfolio_df.empty
    assert len(instruments_df) == 4
    assert len(portfolio_df) == 2
    expected_cols = {"daily_ror", "position_id", "sector", "region"}
    assert expected_cols.issubset(instruments_df.columns)
    assert instruments_df[instruments_df["position_id"] == "Stock_A"]["sector"].iloc[0] == "Technology"
    assert instruments_df[instruments_df["position_id"] == "Stock_B"]["sector"].iloc[0] == "Healthcare"


def test_calculate_daily_contributions_bod_weighting(prepared_data_fixture):
    """Tests that daily contributions are calculated correctly using BOD weighting."""
    instruments_df, portfolio_df = prepared_data_fixture
    result_df = _calculate_daily_instrument_contributions(
        instruments_df, portfolio_df, WeightingScheme.BOD, Smoothing(method="NONE")
    )
    stock_a_day_1 = result_df[result_df["position_id"] == "Stock_A"].iloc[0]
    assert stock_a_day_1["daily_weight"] == pytest.approx(0.6)
    assert stock_a_day_1["raw_contribution"] == pytest.approx(0.012)
    stock_b_day_2 = result_df[result_df["position_id"] == "Stock_B"].iloc[1]
    assert stock_b_day_2["daily_weight"] == pytest.approx(408 / 1070)
    assert stock_b_day_2["raw_contribution"] == pytest.approx(0.001869, abs=1e-6)


def test_calculate_daily_contributions_smoothing(prepared_data_fixture):
    """Tests that Carino smoothing correctly adjusts the raw contribution."""
    instruments_df, portfolio_df = prepared_data_fixture
    result_df = _calculate_daily_instrument_contributions(
        instruments_df, portfolio_df, WeightingScheme.BOD, Smoothing(method="CARINO")
    )
    stock_a_day_1 = result_df[result_df["position_id"] == "Stock_A"].iloc[0]
    assert stock_a_day_1["raw_contribution"] == pytest.approx(0.012)
    assert stock_a_day_1["smoothed_contribution"] != pytest.approx(0.012)
    assert stock_a_day_1["smoothed_contribution"] == pytest.approx(0.01205617, abs=1e-8)


def test_calculate_carino_factors():
    """Tests the Carino smoothing factor calculation."""
    k_daily = _calculate_carino_factors(pd.Series([0.10]))
    assert k_daily.iloc[0] == pytest.approx(0.95310179)
    k_zero = _calculate_carino_factors(pd.Series([0.0]))
    assert k_zero.iloc[0] == 1.0


def test_carino_factors_match_source_docs_two_day_example():
    """Carino industry example: +10% then -10% links to -1% with F_t = k_t / K."""
    ror_series = pd.Series(
        [0.10, -0.10],
        index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
    )

    k_daily = _calculate_carino_factors(ror_series)
    linked_return = float((1 + ror_series).prod() - 1)
    k_total = _calculate_carino_factor_for_return(linked_return)

    assert linked_return == pytest.approx(-0.01)
    assert k_daily.iloc[0] == pytest.approx(0.9531017980)
    assert k_daily.iloc[1] == pytest.approx(1.0536051566)
    assert k_total == pytest.approx(1.0050335854)
    assert k_daily.iloc[0] / k_total == pytest.approx(0.9483283066)
    assert k_daily.iloc[1] / k_total == pytest.approx(1.0483283066)


def test_carino_smoothing_reconciles_raw_daily_mismatch_to_linked_return():
    """Raw daily contributions can fail multi-period linkage until Carino factors are applied."""
    instruments_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "position_id": "P1",
                "begin_mv": 100.0,
                "bod_cf": 0.0,
                "daily_ror": 10.0,
                "local_ror": 10.0,
                "fx_ror": 0.0,
            },
            {
                "perf_date": pd.Timestamp("2025-01-02"),
                "position_id": "P1",
                "begin_mv": 110.0,
                "bod_cf": 0.0,
                "daily_ror": -10.0,
                "local_ror": -10.0,
                "fx_ror": 0.0,
            },
        ]
    )
    portfolio_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "begin_mv": 100.0,
                "bod_cf": 0.0,
                "daily_ror": 10.0,
                "nip": 0,
                "perf_reset": 0,
            },
            {
                "perf_date": pd.Timestamp("2025-01-02"),
                "begin_mv": 110.0,
                "bod_cf": 0.0,
                "daily_ror": -10.0,
                "nip": 0,
                "perf_reset": 0,
            },
        ]
    )

    result_df = _calculate_daily_instrument_contributions(
        instruments_df,
        portfolio_df,
        WeightingScheme.BOD,
        Smoothing(method="CARINO"),
    )

    assert result_df["raw_contribution"].sum() == pytest.approx(0.0)
    assert result_df["smoothed_contribution"].sum() == pytest.approx(-0.01)
    assert result_df["carino_factor"].tolist() == pytest.approx([0.9483283066, 1.0483283066])


def test_carino_smoothing_handles_zero_linked_return():
    instruments_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "position_id": "P1",
                "begin_mv": 100.0,
                "bod_cf": 0.0,
                "daily_ror": 10.0,
                "local_ror": 10.0,
                "fx_ror": 0.0,
            },
            {
                "perf_date": pd.Timestamp("2025-01-02"),
                "position_id": "P1",
                "begin_mv": 110.0,
                "bod_cf": 0.0,
                "daily_ror": -9.090909090909,
                "local_ror": -9.090909090909,
                "fx_ror": 0.0,
            },
        ]
    )
    portfolio_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "begin_mv": 100.0,
                "bod_cf": 0.0,
                "daily_ror": 10.0,
                "nip": 0,
                "perf_reset": 0,
            },
            {
                "perf_date": pd.Timestamp("2025-01-02"),
                "begin_mv": 110.0,
                "bod_cf": 0.0,
                "daily_ror": -9.090909090909,
                "nip": 0,
                "perf_reset": 0,
            },
        ]
    )

    result_df = _calculate_daily_instrument_contributions(
        instruments_df,
        portfolio_df,
        WeightingScheme.BOD,
        Smoothing(method="CARINO"),
    )

    assert result_df["K_total"].iloc[0] == pytest.approx(1.0)
    assert result_df["smoothed_contribution"].sum() == pytest.approx(0.0, abs=1e-12)


def test_carino_factor_uses_neutral_value_for_near_zero_return():
    assert _calculate_carino_factor_for_return(1e-14) == 1.0


def test_calculate_carino_factor_uses_neutral_fallback_when_log_domain_breaks():
    """Carino should stop smoothing once the linked gross return factor is non-positive."""
    assert _calculate_carino_factor_for_return(-1.0) == 1.0
    assert _calculate_carino_factor_for_return(-1.5) == 1.0


def test_carino_smoothing_domain_is_invalid_for_broken_capital_paths():
    """A daily return of -100% or worse invalidates Carino's logarithmic smoothing domain."""
    assert _carino_smoothing_domain_is_valid(pd.Series([0.10, -0.25])) is True
    assert _carino_smoothing_domain_is_valid(pd.Series([0.10, -1.0])) is False
    assert _carino_smoothing_domain_is_valid(pd.Series([-1.5])) is False


def test_calculate_daily_contributions_returns_empty_for_empty_instruments(prepared_data_fixture):
    _, portfolio_df = prepared_data_fixture
    empty_instruments = pd.DataFrame()
    result_df = _calculate_daily_instrument_contributions(
        empty_instruments, portfolio_df, WeightingScheme.BOD, Smoothing(method="NONE")
    )
    assert result_df.empty


def test_calculate_daily_contributions_zero_portfolio_capital_forces_zero_weight():
    instruments_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "position_id": "P1",
                "begin_mv": 50.0,
                "bod_cf": 0.0,
                "daily_ror": 2.0,
                "local_ror": 2.0,
                "fx_ror": 0.0,
            }
        ]
    )
    portfolio_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "begin_mv": 0.0,
                "bod_cf": 0.0,
                "daily_ror": 0.0,
                "nip": 0,
                "perf_reset": 0,
            }
        ]
    )

    result_df = _calculate_daily_instrument_contributions(
        instruments_df, portfolio_df, WeightingScheme.BOD, Smoothing(method="NONE")
    )

    row = result_df.iloc[0]
    assert row["daily_weight"] == 0.0
    assert row["raw_contribution"] == 0.0
    assert row["raw_local_contribution"] == 0.0
    assert row["raw_fx_contribution"] == 0.0


def test_calculate_daily_contributions_uses_raw_fallback_when_carino_domain_breaks():
    """Reset-heavy broken-capital episodes should not emit invalid Carino adjustments."""
    instruments_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "position_id": "P1",
                "begin_mv": 100.0,
                "bod_cf": 0.0,
                "daily_ror": -150.0,
                "local_ror": -150.0,
                "fx_ror": 0.0,
            }
        ]
    )
    portfolio_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "begin_mv": 100.0,
                "bod_cf": 0.0,
                "daily_ror": -150.0,
                "nip": 0,
                "perf_reset": 0,
            }
        ]
    )

    result_df = _calculate_daily_instrument_contributions(
        instruments_df, portfolio_df, WeightingScheme.BOD, Smoothing(method="CARINO")
    )

    row = result_df.iloc[0]
    assert row["raw_contribution"] == pytest.approx(-1.5)
    assert row["smoothed_contribution"] == pytest.approx(row["raw_contribution"])


def test_prepare_hierarchical_data_returns_empty_instruments_when_positions_missing(happy_path_payload):
    payload = happy_path_payload.copy()
    payload["hierarchy"] = ["sector"]
    payload["positions_data"] = [{"position_id": "EMPTY", "meta": {"sector": "NA"}, "valuation_points": []}]
    request = ContributionRequest.model_validate(payload)

    instruments_df, portfolio_df = _prepare_hierarchical_data(request)
    assert instruments_df.empty
    assert not portfolio_df.empty


def test_calculate_hierarchical_contribution_includes_currency_breakdown_for_both_mode(happy_path_payload, mocker):
    payload = happy_path_payload.copy()
    payload["hierarchy"] = ["sector"]
    payload["currency_mode"] = "BOTH"
    payload["report_ccy"] = "USD"
    request = ContributionRequest.model_validate(payload)

    instruments_df = pd.DataFrame(
        [
            {
                "position_id": "P1",
                "sector": "Tech",
                "daily_weight": 1.0,
                "smoothed_contribution": 0.01,
                "smoothed_local_contribution": 0.006,
                "smoothed_fx_contribution": 0.004,
            }
        ]
    )
    mocker.patch(
        "engine.contribution._prepare_hierarchical_data",
        return_value=(pd.DataFrame(), pd.DataFrame({"daily_ror": [1.0]})),
    )
    mocker.patch("engine.contribution._calculate_daily_instrument_contributions", return_value=instruments_df)

    results, _ = calculate_hierarchical_contribution(request)
    first_row = results["levels"][0]["rows"][0]
    assert "local_contribution" in first_row
    assert "fx_contribution" in first_row
    assert "local_contribution" in results["summary"]
    assert "fx_contribution" in results["summary"]


def test_build_hierarchical_contribution_result_empty_daily_data_preserves_currency_breakout(
    hierarchical_request_fixture,
):
    request = hierarchical_request_fixture.model_copy(update={"currency_mode": "BOTH"})

    result = build_hierarchical_contribution_result(
        pd.DataFrame(),
        request,
        total_portfolio_return=0.0,
    )

    assert result == {
        "summary": {
            "portfolio_contribution": 0.0,
            "coverage_mv_pct": 100.0,
            "weighting_scheme": request.weighting_scheme.value,
            "local_contribution": 0.0,
            "fx_contribution": 0.0,
        },
        "levels": [],
    }


def test_base_only_engine_config_preserves_non_currency_settings():
    config = EngineConfig(
        performance_start_date=pd.Timestamp("2025-01-01").date(),
        report_start_date=pd.Timestamp("2025-01-02").date(),
        report_end_date=pd.Timestamp("2025-01-31").date(),
        metric_basis="NET",
        period_type=PeriodType.YTD,
        rounding_precision=6,
        precision_mode=PrecisionMode.DECIMAL_STRICT,
        currency_mode="BOTH",
        report_ccy="EUR",
    )

    overridden = base_only_engine_config(config)

    assert overridden.currency_mode == "BASE_ONLY"
    assert overridden.rounding_precision == 6
    assert overridden.precision_mode == PrecisionMode.DECIMAL_STRICT
    assert overridden.report_ccy == "EUR"
