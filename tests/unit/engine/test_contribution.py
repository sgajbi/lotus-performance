# tests/unit/engine/test_contribution.py
import pandas as pd
import pytest

from app.models.contribution_requests import ContributionRequest, Smoothing
from common.enums import WeightingScheme
from engine.contribution import (
    _calculate_carino_factors,
    _calculate_daily_instrument_contributions,
    _prepare_hierarchical_data,
    calculate_hierarchical_contribution,
)


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
                {"day": 1, "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408},
                {"day": 2, "perf_date": "2025-01-02", "begin_mv": 408, "end_mv": 410},
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
    assert stock_a_day_1["smoothed_contribution"] == pytest.approx(0.01194, abs=1e-5)


def test_calculate_carino_factors():
    """Tests the Carino smoothing factor calculation."""
    k_daily = _calculate_carino_factors(pd.Series([0.10]))
    assert k_daily.iloc[0] == pytest.approx(0.95310179)
    k_zero = _calculate_carino_factors(pd.Series([0.0]))
    assert k_zero.iloc[0] == 1.0


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
