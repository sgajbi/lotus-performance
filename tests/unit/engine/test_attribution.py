# tests/unit/engine/test_attribution.py
import pandas as pd
import pytest

from app.models.attribution_requests import AttributionRequest
from common.enums import AttributionModel
from engine.attribution import (
    _align_and_prepare_data,
    _calculate_currency_attribution_effects,
    _calculate_single_period_effects,
    _link_effects_top_down,
    _prepare_data_from_instruments,
    _prepare_panel_from_groups,
    aggregate_attribution_results,
    run_attribution_calculations,
)


@pytest.fixture
def single_period_data():
    """Provides aligned data for a single period for attribution testing."""
    data = {
        "group": ["Equity", "Bonds", "Cash"],
        "w_p": [0.60, 0.30, 0.10],
        "r_base_p": [0.10, 0.04, 0.01],
        "w_b": [0.50, 0.40, 0.10],
        "r_base_b": [0.08, 0.03, 0.01],
    }
    df = pd.DataFrame(data).set_index("group")
    df["r_b_total"] = (df["w_b"] * df["r_base_b"]).sum()
    return df


@pytest.fixture
def by_group_request_data():
    """Provides a sample AttributionRequest for by_group mode where weights sum to 1."""
    return {
        "portfolio_id": "ATTRIB_UNIT_TEST_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "model": "BF",
        "linking": "carino",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-02-28",
        "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [
                    {"date": "2025-01-31", "return_base": 0.02, "weight_bop": 0.5},
                    {"date": "2025-02-28", "return_base": 0.01, "weight_bop": 0.6},
                ],
            },
            {
                "key": {"sector": "Other"},
                "observations": [
                    {"date": "2025-01-31", "return_base": 0.01, "weight_bop": 0.5},
                    {"date": "2025-02-28", "return_base": 0.005, "weight_bop": 0.4},
                ],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [
                    {"date": "2025-01-31", "return_base": 0.01, "weight_bop": 0.4},
                    {"date": "2025-02-28", "return_base": -0.01, "weight_bop": 0.45},
                ],
            },
            {
                "key": {"sector": "Other"},
                "observations": [
                    {"date": "2025-01-31", "return_base": 0.005, "weight_bop": 0.6},
                    {"date": "2025-02-28", "return_base": 0.002, "weight_bop": 0.55},
                ],
            },
        ],
    }


def test_align_and_prepare_data_by_group(by_group_request_data):
    """Tests the data preparation and alignment logic for a by_group request."""
    request = AttributionRequest.model_validate(by_group_request_data)
    aligned_df = _align_and_prepare_data(request, request.portfolio_groups_data)
    assert not aligned_df.empty
    assert aligned_df.index.names == ["date", "sector"]


def test_calculate_single_period_brinson_fachler(single_period_data):
    """Tests the Brinson-Fachler model calculation for a single period."""
    result_df = _calculate_single_period_effects(single_period_data, AttributionModel.BRINSON_FACHLER)
    total_effects = result_df[["allocation", "selection", "interaction"]].sum().sum()
    assert total_effects == pytest.approx(0.020)


def test_calculate_single_period_brinson_hood_beebower(single_period_data):
    """Tests the Brinson-Hood-Beebower model calculation for a single period."""
    result_df = _calculate_single_period_effects(single_period_data, AttributionModel.BRINSON_HOOD_BEEBOWER)
    total_effects = result_df[["allocation", "selection", "interaction"]].sum().sum()
    assert total_effects == pytest.approx(0.021)


def test_calculate_single_period_effects_matches_exact_brinson_fachler_formulas():
    df = pd.DataFrame(
        {
            "w_p": [0.60],
            "w_b": [0.50],
            "r_base_p": [0.05],
            "r_base_b": [0.04],
            "r_b_total": [0.03],
        }
    )

    result_df = _calculate_single_period_effects(df.copy(), AttributionModel.BRINSON_FACHLER)

    row = result_df.iloc[0]
    assert row["allocation"] == pytest.approx((0.60 - 0.50) * (0.04 - 0.03))
    assert row["selection"] == pytest.approx(0.50 * (0.05 - 0.04))
    assert row["interaction"] == pytest.approx((0.60 - 0.50) * (0.05 - 0.04))


def test_calculate_single_period_effects_matches_exact_brinson_hood_beebower_formulas():
    df = pd.DataFrame(
        {
            "w_p": [0.60],
            "w_b": [0.50],
            "r_base_p": [0.05],
            "r_base_b": [0.04],
            "r_b_total": [0.03],
        }
    )

    result_df = _calculate_single_period_effects(df.copy(), AttributionModel.BRINSON_HOOD_BEEBOWER)

    row = result_df.iloc[0]
    assert row["allocation"] == pytest.approx((0.60 - 0.50) * 0.04)
    assert row["selection"] == pytest.approx(0.60 * (0.05 - 0.04))
    assert row["interaction"] == pytest.approx((0.60 - 0.50) * (0.05 - 0.04))


def test_run_attribution_calculations_and_aggregation(by_group_request_data):
    """Tests the two-stage process: first calculate daily effects, then aggregate."""
    by_group_request_data["linking"] = "none"
    request = AttributionRequest.model_validate(by_group_request_data)

    effects_df, _ = run_attribution_calculations(request)
    assert isinstance(effects_df, pd.DataFrame)
    assert "allocation" in effects_df.columns

    final_result, _ = aggregate_attribution_results(effects_df, request)
    assert abs(final_result.reconciliation.residual) < 1e-9


def test_run_attribution_calculations_geometric_linking(by_group_request_data):
    """Tests the main orchestrator with top-down geometric linking enabled."""
    request = AttributionRequest.model_validate(by_group_request_data)
    effects_df, _ = run_attribution_calculations(request)
    final_result, _ = aggregate_attribution_results(effects_df, request)

    assert abs(final_result.reconciliation.residual) < 1e-9
    assert final_result.reconciliation.sum_of_effects == pytest.approx(final_result.reconciliation.total_active_return)


def test_prepare_data_from_instruments():
    """Tests the aggregation of instrument data into portfolio groups."""
    daily_data_p = [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1025}]
    daily_data_aapl = [{"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 624}]
    daily_data_msft = [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 401}]

    request_data = {
        "portfolio_id": "TEST",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {"metric_basis": "NET", "valuation_points": daily_data_p},
        "instruments_data": [
            {"instrument_id": "AAPL", "meta": {"sector": "Tech"}, "valuation_points": daily_data_aapl},
            {"instrument_id": "MSFT", "meta": {"sector": "Tech"}, "valuation_points": daily_data_msft},
        ],
        "benchmark_groups_data": [],
    }
    request = AttributionRequest.model_validate(request_data)

    result_groups = _prepare_data_from_instruments(request)

    assert len(result_groups) == 1
    tech_group = result_groups[0]
    obs = tech_group.observations[0]

    assert obs["weight_bop"] == pytest.approx(1.0)
    assert obs["return_base"] == pytest.approx(0.025)


def test_prepare_data_from_instruments_missing_portfolio_data():
    """Tests that a ValueError is raised if portfolio_data is missing in by_instrument mode."""
    request_data = {
        "portfolio_id": "TEST",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "instruments_data": [],
        "benchmark_groups_data": [],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
    }
    request = AttributionRequest.model_validate(request_data)
    with pytest.raises(ValueError, match="'portfolio_data' and 'instruments_data' are required"):
        _prepare_data_from_instruments(request)


def test_prepare_data_from_instruments_returns_empty_when_all_inputs_empty():
    request_data = {
        "portfolio_id": "TEST",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1000}],
        },
        "instruments_data": [{"instrument_id": "EMPTY", "meta": {"sector": "Tech"}, "valuation_points": []}],
        "benchmark_groups_data": [],
    }
    request = AttributionRequest.model_validate(request_data)
    assert _prepare_data_from_instruments(request) == []


def test_prepare_data_from_instruments_zero_portfolio_capital_forces_zero_group_weight():
    request_data = {
        "portfolio_id": "TEST",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 0, "bod_cf": 0, "end_mv": 0}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"sector": "Tech"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 50, "end_mv": 51}],
            }
        ],
        "benchmark_groups_data": [],
    }
    request = AttributionRequest.model_validate(request_data)

    result_groups = _prepare_data_from_instruments(request)

    assert len(result_groups) == 1
    obs = result_groups[0].observations[0]
    assert obs["weight_bop"] == 0.0
    assert obs["return_base"] == 0.0


def test_prepare_panel_from_groups_handles_empty_cases():
    assert _prepare_panel_from_groups([], ["sector"]).empty

    class _EmptyGroup:
        key = {"sector": "Tech"}
        observations = []

    assert _prepare_panel_from_groups([_EmptyGroup()], ["sector"]).empty


def test_align_and_prepare_data_returns_empty_when_benchmark_missing(by_group_request_data):
    request_payload = by_group_request_data.copy()
    request_payload["benchmark_groups_data"] = []
    request = AttributionRequest.model_validate(request_payload)
    aligned_df = _align_and_prepare_data(request, request.portfolio_groups_data)
    assert aligned_df.empty


def test_link_effects_top_down_noop_when_arithmetic_total_zero():
    effects_df = pd.DataFrame({"allocation": [0.1], "selection": [0.2], "interaction": [-0.3]})
    result = _link_effects_top_down(effects_df, geometric_total_ar=0.05, arithmetic_total_ar=0.0)
    pd.testing.assert_frame_equal(result, effects_df)


def test_link_effects_top_down_scales_only_effect_columns():
    effects_df = pd.DataFrame(
        {
            "allocation": [0.10, 0.20],
            "selection": [0.05, 0.15],
            "interaction": [0.02, 0.03],
            "sector": ["Tech", "Health"],
        }
    )

    result = _link_effects_top_down(effects_df, geometric_total_ar=0.25, arithmetic_total_ar=0.50)

    assert result["allocation"].tolist() == pytest.approx([0.05, 0.10])
    assert result["selection"].tolist() == pytest.approx([0.025, 0.075])
    assert result["interaction"].tolist() == pytest.approx([0.01, 0.015])
    assert result["sector"].tolist() == ["Tech", "Health"]


def test_calculate_currency_attribution_effects_matches_exact_formulas():
    df = pd.DataFrame(
        {
            "w_p": [0.55],
            "w_b": [0.50],
            "r_local_p": [0.025],
            "r_local_b": [0.020],
            "r_fx_b": [0.010],
        }
    )

    result_df = _calculate_currency_attribution_effects(df.copy())
    row = result_df.iloc[0]

    assert row["local_allocation"] == pytest.approx((0.55 - 0.50) * 0.020)
    assert row["local_selection"] == pytest.approx(0.50 * (0.025 - 0.020))
    assert row["currency_allocation"] == pytest.approx((0.55 - 0.50) * (1 + 0.020) * 0.010)
    assert row["currency_selection"] == pytest.approx(0.50 * (0.025 - 0.020) * 0.010)


def test_run_attribution_calculations_invalid_mode_raises_value_error():
    class _UnsupportedRequest:
        mode = "unsupported"

    with pytest.raises(ValueError, match="Invalid attribution mode specified"):
        run_attribution_calculations(_UnsupportedRequest())


def test_run_attribution_calculations_returns_empty_when_aligned_panel_empty(by_group_request_data):
    request_payload = by_group_request_data.copy()
    request_payload["portfolio_groups_data"] = []
    request = AttributionRequest.model_validate(request_payload)
    effects_df, lineage = run_attribution_calculations(request)

    assert effects_df.empty
    assert "aligned_panel.csv" in lineage
