# tests/unit/engine/test_contribution.py
from dataclasses import dataclass

import pandas as pd
import pytest

from app.models.contribution_requests import ContributionRequest, Smoothing
from common.enums import WeightingScheme
from engine.config import EngineConfig, PeriodType, PrecisionMode
from engine.contribution import (
    _apply_carino_residual_allocation,
    _apply_position_fx_capital_conversion,
    _build_contribution_fx_rates_frame,
    _build_contribution_twr_config,
    _build_hierarchical_response_levels,
    _calculate_carino_factor_for_return,
    _calculate_carino_factors,
    _calculate_daily_instrument_contributions,
    _carino_smoothing_domain_is_valid,
    _ensure_same_currency_local_fx_columns,
    _prepare_hierarchical_data,
    _requires_position_fx_capital_conversion,
    build_hierarchical_contribution_result,
    calculate_hierarchical_contribution,
)
from engine.contribution_smoothing import apply_contribution_smoothing
from engine.runtime import base_only_engine_config


@dataclass(frozen=True)
class StructuralSmoothing:
    method: str


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


def test_build_contribution_twr_config_uses_request_window_and_portfolio_start(hierarchical_request_fixture):
    config = _build_contribution_twr_config(hierarchical_request_fixture)

    assert config.performance_start_date == hierarchical_request_fixture.portfolio_data.valuation_points[0].perf_date
    assert config.report_start_date == hierarchical_request_fixture.report_start_date
    assert config.report_end_date == hierarchical_request_fixture.report_end_date
    assert config.metric_basis == hierarchical_request_fixture.portfolio_data.metric_basis


def test_build_contribution_fx_rates_frame_normalizes_dates_and_keeps_latest_duplicate(happy_path_payload):
    payload = happy_path_payload.copy()
    payload["currency_mode"] = "BOTH"
    payload["report_ccy"] = "USD"
    payload["fx"] = {
        "rates": [
            {"date": "2025-01-01", "ccy": "EUR", "rate": 1.1},
            {"date": "2025-01-01", "ccy": "EUR", "rate": 1.2},
            {"date": "2025-01-02", "ccy": "EUR", "rate": 1.3},
        ]
    }
    request = ContributionRequest.model_validate(payload)

    fx_rates_df = _build_contribution_fx_rates_frame(request)

    assert len(fx_rates_df) == 2
    assert fx_rates_df["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-01-01", "2025-01-02"]
    assert fx_rates_df["rate"].tolist() == [1.2, 1.3]


def test_ensure_same_currency_local_fx_columns_fills_base_only_position_results(hierarchical_request_fixture):
    request = hierarchical_request_fixture.model_copy(update={"currency_mode": "BOTH", "report_ccy": "USD"})
    position_results_df = pd.DataFrame({"daily_ror": [1.25]})

    _ensure_same_currency_local_fx_columns(
        position_results_df=position_results_df,
        request=request,
        position_ccy="USD",
    )

    assert position_results_df["local_ror"].tolist() == [1.25]
    assert position_results_df["fx_ror"].tolist() == [0.0]


@pytest.mark.parametrize(
    ("currency_mode", "position_ccy", "report_ccy", "has_fx_rates", "expected"),
    [
        ("BOTH", "EUR", "USD", True, True),
        ("BASE_ONLY", "EUR", "USD", True, False),
        ("BOTH", "USD", "USD", True, False),
        ("BOTH", "EUR", "USD", False, False),
    ],
)
def test_requires_position_fx_capital_conversion_checks_currency_mode_position_currency_and_rates(
    hierarchical_request_fixture,
    currency_mode,
    position_ccy,
    report_ccy,
    has_fx_rates,
    expected,
):
    request = hierarchical_request_fixture.model_copy(update={"currency_mode": currency_mode, "report_ccy": report_ccy})
    fx_rates_df = pd.DataFrame({"date": [pd.Timestamp("2025-01-01")], "ccy": [position_ccy], "rate": [1.2]})
    if not has_fx_rates:
        fx_rates_df = pd.DataFrame()

    assert (
        _requires_position_fx_capital_conversion(
            request=request,
            position_ccy=position_ccy,
            fx_rates_df=fx_rates_df,
        )
        is expected
    )


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


def test_apply_contribution_smoothing_accepts_structural_smoothing_config():
    contribution_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "raw_local_contribution": 0.01,
                "raw_fx_contribution": 0.002,
                "raw_contribution": 0.012,
            }
        ]
    )
    portfolio_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "daily_ror": 1.2,
            }
        ]
    )

    result_df = apply_contribution_smoothing(contribution_df, portfolio_df, StructuralSmoothing(method="NONE"))

    row = result_df.iloc[0]
    assert row["smoothed_local_contribution"] == pytest.approx(0.01)
    assert row["smoothed_fx_contribution"] == pytest.approx(0.002)
    assert row["smoothed_contribution"] == pytest.approx(0.012)


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


def test_calculate_daily_contributions_uses_precomputed_capital_for_non_bod_weighting():
    instruments_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "position_id": "P1",
                "begin_mv": 50.0,
                "bod_cf": 0.0,
                "capital_inst": 25.0,
                "capital_port": 100.0,
                "daily_ror": 8.0,
                "local_ror": 5.0,
                "fx_ror": 3.0,
            }
        ]
    )
    portfolio_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-01"),
                "begin_mv": 200.0,
                "bod_cf": 0.0,
                "daily_ror": 8.0,
                "nip": 0,
                "perf_reset": 0,
            }
        ]
    )

    result_df = _calculate_daily_instrument_contributions(
        instruments_df,
        portfolio_df,
        WeightingScheme.AVG_CAPITAL,
        Smoothing(method="NONE"),
    )

    row = result_df.iloc[0]
    assert row["daily_weight"] == pytest.approx(0.25)
    assert row["raw_contribution"] == pytest.approx(0.02)
    assert row["raw_local_contribution"] == pytest.approx(0.0125)
    assert row["raw_fx_contribution"] == pytest.approx(0.0075)


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


def test_apply_position_fx_capital_conversion_uses_prior_day_rate(hierarchical_request_fixture):
    request = hierarchical_request_fixture.model_copy(update={"currency_mode": "BOTH", "report_ccy": "USD"})
    position_results_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-02"),
                "begin_mv": 100.0,
                "bod_cf": 5.0,
            }
        ]
    )
    fx_rates_df = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-01-01"), "ccy": "EUR", "rate": 1.2},
            {"date": pd.Timestamp("2025-01-02"), "ccy": "EUR", "rate": 1.4},
        ]
    )

    converted_df = _apply_position_fx_capital_conversion(
        position_results_df=position_results_df,
        request=request,
        position_ccy="EUR",
        fx_rates_df=fx_rates_df,
    )

    row = converted_df.iloc[0]
    assert "_position_fx_conversion_rate" not in converted_df.columns
    assert row["begin_mv"] == pytest.approx(120.0)
    assert row["bod_cf"] == pytest.approx(6.0)


def test_apply_position_fx_capital_conversion_preserves_metadata_rate_columns(
    hierarchical_request_fixture,
):
    request = hierarchical_request_fixture.model_copy(update={"currency_mode": "BOTH", "report_ccy": "USD"})
    position_results_df = pd.DataFrame(
        [
            {
                "perf_date": pd.Timestamp("2025-01-02"),
                "begin_mv": 100.0,
                "bod_cf": 5.0,
                "fx_rate": 99.0,
                "_position_fx_conversion_rate": 88.0,
            }
        ]
    )
    fx_rates_df = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-01-01"), "ccy": "EUR", "rate": 1.2},
            {"date": pd.Timestamp("2025-01-02"), "ccy": "EUR", "rate": 1.4},
        ]
    )

    converted_df = _apply_position_fx_capital_conversion(
        position_results_df=position_results_df,
        request=request,
        position_ccy="EUR",
        fx_rates_df=fx_rates_df,
    )

    row = converted_df.iloc[0]
    assert row["fx_rate"] == pytest.approx(99.0)
    assert row["_position_fx_conversion_rate"] == pytest.approx(88.0)
    assert row["begin_mv"] == pytest.approx(120.0)
    assert row["bod_cf"] == pytest.approx(6.0)


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


def test_build_hierarchical_contribution_result_empty_daily_data_omits_currency_breakout_for_base_only(
    hierarchical_request_fixture,
):
    result = build_hierarchical_contribution_result(
        pd.DataFrame(),
        hierarchical_request_fixture,
        total_portfolio_return=0.0,
    )

    assert result == {
        "summary": {
            "portfolio_contribution": 0.0,
            "coverage_mv_pct": 100.0,
            "weighting_scheme": hierarchical_request_fixture.weighting_scheme.value,
        },
        "levels": [],
    }


def test_build_hierarchical_contribution_result_base_only_summary_omits_currency_breakout(
    hierarchical_request_fixture,
):
    request = hierarchical_request_fixture.model_copy(update={"hierarchy": None})
    daily_contributions_df = pd.DataFrame(
        [
            {
                "position_id": "P1",
                "daily_weight": 0.4,
                "smoothed_contribution": 0.01,
                "smoothed_local_contribution": 0.006,
                "smoothed_fx_contribution": 0.004,
            },
            {
                "position_id": "P2",
                "daily_weight": 0.6,
                "smoothed_contribution": 0.02,
                "smoothed_local_contribution": 0.014,
                "smoothed_fx_contribution": 0.006,
            },
        ]
    )

    result = build_hierarchical_contribution_result(
        daily_contributions_df,
        request,
        total_portfolio_return=0.03,
    )

    assert result["summary"] == {
        "portfolio_contribution": pytest.approx(3.0),
        "coverage_mv_pct": 100.0,
        "weighting_scheme": request.weighting_scheme.value,
    }
    assert result["levels"] == []


def test_build_hierarchical_response_levels_projects_parent_and_currency_rows():
    aggregated_df = pd.DataFrame(
        [
            {
                "sector": "Tech",
                "region": "US",
                "contribution": 0.01,
                "local_contribution": 0.006,
                "fx_contribution": 0.004,
                "weight_avg": 0.6,
            },
            {
                "sector": "Tech",
                "region": "EU",
                "contribution": 0.02,
                "local_contribution": 0.015,
                "fx_contribution": 0.005,
                "weight_avg": 0.4,
            },
        ]
    )

    levels = _build_hierarchical_response_levels(
        aggregated_df=aggregated_df,
        hierarchy=["sector", "region"],
        currency_mode="BOTH",
    )

    assert levels[0]["parent"] is None
    assert levels[0]["rows"] == [
        {
            "key": {"sector": "Tech"},
            "contribution": pytest.approx(3.0),
            "weight_avg": pytest.approx(100.0),
            "local_contribution": pytest.approx(2.1),
            "fx_contribution": pytest.approx(0.9),
        }
    ]
    assert levels[1]["parent"] == "sector"
    assert [row["key"] for row in levels[1]["rows"]] == [
        {"sector": "Tech", "region": "EU"},
        {"sector": "Tech", "region": "US"},
    ]


def test_build_hierarchical_response_levels_omits_currency_rows_for_base_only():
    aggregated_df = pd.DataFrame(
        [
            {
                "sector": "Tech",
                "contribution": 0.01,
                "local_contribution": 0.006,
                "fx_contribution": 0.004,
                "weight_avg": 0.6,
            }
        ]
    )

    levels = _build_hierarchical_response_levels(
        aggregated_df=aggregated_df,
        hierarchy=["sector"],
        currency_mode="BASE_ONLY",
    )

    assert levels == [
        {
            "level": 1,
            "name": "sector",
            "parent": None,
            "rows": [
                {
                    "key": {"sector": "Tech"},
                    "contribution": pytest.approx(1.0),
                    "weight_avg": pytest.approx(60.0),
                }
            ],
        }
    ]


def test_apply_carino_residual_allocation_distributes_total_local_and_fx_residuals():
    totals = pd.DataFrame(
        [
            {"contribution": 0.06, "local_contribution": 0.04, "fx_contribution": 0.02, "weight_avg": 0.75},
            {"contribution": 0.02, "local_contribution": 0.01, "fx_contribution": 0.01, "weight_avg": 0.25},
        ]
    )

    _apply_carino_residual_allocation(totals, total_portfolio_return=0.1, smoothing_method="CARINO")

    assert totals["contribution"].sum() == pytest.approx(0.1)
    assert totals["local_contribution"].sum() == pytest.approx(0.0625)
    assert totals["fx_contribution"].sum() == pytest.approx(0.0375)
    assert totals["weight_proportion"].tolist() == pytest.approx([0.75, 0.25])


def test_apply_carino_residual_allocation_noops_for_non_carino_method():
    totals = pd.DataFrame(
        [
            {"contribution": 0.06, "local_contribution": 0.04, "fx_contribution": 0.02, "weight_avg": 0.75},
            {"contribution": 0.02, "local_contribution": 0.01, "fx_contribution": 0.01, "weight_avg": 0.25},
        ]
    )
    original = totals.copy(deep=True)

    _apply_carino_residual_allocation(totals, total_portfolio_return=0.1, smoothing_method="NONE")

    pd.testing.assert_frame_equal(totals, original)


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
