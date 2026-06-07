# tests/unit/engine/test_attribution.py
import pandas as pd
import pytest

from app.models.attribution_requests import AttributionRequest
from common.enums import AttributionModel
from engine.attribution import (
    _align_and_prepare_data,
    _build_group_key_dict,
    _build_instrument_attribution_panel,
    _calculate_currency_attribution_effects,
    _calculate_group_context_metrics,
    _calculate_single_period_effects,
    _link_effects_top_down,
    _normalize_instrument_group_columns,
    _normalize_instrument_return_columns,
    _prepare_data_from_instruments,
    _prepare_panel_from_groups,
    aggregate_attribution_results,
    run_attribution_calculations,
)
from engine.attribution_supportability import classify_attribution_residual
from engine.config import EngineConfig


def _build_test_twr_config(request: AttributionRequest) -> EngineConfig:
    return EngineConfig(
        performance_start_date=request.report_start_date,
        report_start_date=request.report_start_date,
        report_end_date=request.report_end_date,
        metric_basis=request.portfolio_data.metric_basis,
        period_type=request.analyses[0].period,
        currency_mode=request.currency_mode,
        report_ccy=request.report_ccy,
        fx=request.fx,
        hedging=request.hedging,
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


def test_calculate_single_period_brinson_fachler_matches_industry_regression_pack_case_a():
    df = pd.DataFrame(
        {
            "group": ["Equity", "Bonds", "Cash"],
            "w_p": [0.60, 0.30, 0.10],
            "r_base_p": [0.12, 0.04, 0.01],
            "w_b": [0.50, 0.40, 0.10],
            "r_base_b": [0.10, 0.05, 0.01],
        }
    ).set_index("group")
    df["r_b_total"] = (df["w_b"] * df["r_base_b"]).sum()

    result_df = _calculate_single_period_effects(df.copy(), AttributionModel.BRINSON_FACHLER)
    expected = {
        "Equity": {"allocation": 0.0029, "selection": 0.0100, "interaction": 0.0020},
        "Bonds": {"allocation": 0.0021, "selection": -0.0040, "interaction": 0.0010},
        "Cash": {"allocation": 0.0000, "selection": 0.0000, "interaction": 0.0000},
    }

    for group, group_expected in expected.items():
        for effect, value in group_expected.items():
            assert result_df.loc[group, effect] == pytest.approx(value, abs=1e-12)
        assert result_df.loc[group, ["allocation", "selection", "interaction"]].sum() == pytest.approx(
            result_df.loc[group, "w_p"] * result_df.loc[group, "r_base_p"]
            - result_df.loc[group, "w_b"] * result_df.loc[group, "r_base_b"]
            - (result_df.loc[group, "w_p"] - result_df.loc[group, "w_b"]) * result_df.loc[group, "r_b_total"],
            abs=1e-12,
        )

    portfolio_return = (result_df["w_p"] * result_df["r_base_p"]).sum()
    benchmark_return = (result_df["w_b"] * result_df["r_base_b"]).sum()
    active_contribution = (result_df["w_p"] * result_df["r_base_p"]) - (result_df["w_b"] * result_df["r_base_b"])
    total_effect = result_df[["allocation", "selection", "interaction"]].sum().sum()

    assert portfolio_return == pytest.approx(0.085, abs=1e-12)
    assert benchmark_return == pytest.approx(0.071, abs=1e-12)
    assert active_contribution.sum() == pytest.approx(0.014, abs=1e-12)
    assert total_effect == pytest.approx(0.014, abs=1e-12)


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


def test_aggregate_attribution_results_emits_side_by_side_group_context(by_group_request_data):
    request_payload = by_group_request_data.copy()
    request_payload["linking"] = "none"
    request = AttributionRequest.model_validate(request_payload)

    effects_df, _ = run_attribution_calculations(request)
    final_result, _ = aggregate_attribution_results(effects_df, request)

    tech_group = next(group for group in final_result.levels[0].groups if group.key["sector"] == "Tech")

    assert tech_group.portfolio_weight_avg == pytest.approx(55.0)
    assert tech_group.benchmark_weight_avg == pytest.approx(42.5)
    assert tech_group.portfolio_return == pytest.approx(3.02)
    assert tech_group.benchmark_return == pytest.approx(-0.01)


def test_attribution_segment_union_and_order_independence_for_portfolio_and_benchmark_only_groups():
    def _request(portfolio_groups, benchmark_groups):
        return AttributionRequest.model_validate(
            {
                "portfolio_id": "ATTR_SEGMENT_UNION",
                "mode": "by_group",
                "group_by": ["sector"],
                "model": "BF",
                "linking": "none",
                "frequency": "daily",
                "report_start_date": "2025-01-01",
                "report_end_date": "2025-01-01",
                "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
                "portfolio_groups_data": portfolio_groups,
                "benchmark_groups_data": benchmark_groups,
            }
        )

    portfolio_groups = [
        {"key": {"sector": "Equity"}, "observations": [{"date": "2025-01-01", "return_base": 0.07, "weight_bop": 0.8}]},
        {
            "key": {"sector": "Alternatives"},
            "observations": [{"date": "2025-01-01", "return_base": 0.09, "weight_bop": 0.2}],
        },
    ]
    benchmark_groups = [
        {"key": {"sector": "Equity"}, "observations": [{"date": "2025-01-01", "return_base": 0.06, "weight_bop": 0.8}]},
        {
            "key": {"sector": "Real Estate"},
            "observations": [{"date": "2025-01-01", "return_base": 0.10, "weight_bop": 0.2}],
        },
    ]

    request = _request(portfolio_groups, benchmark_groups)
    reversed_request = _request(list(reversed(portfolio_groups)), list(reversed(benchmark_groups)))

    effects_df, _ = run_attribution_calculations(request)
    reversed_effects_df, _ = run_attribution_calculations(reversed_request)
    result, _ = aggregate_attribution_results(effects_df, request)
    reversed_result, _ = aggregate_attribution_results(reversed_effects_df, reversed_request)

    groups = {group.key["sector"]: group for group in result.levels[0].groups}
    reversed_groups = {group.key["sector"]: group for group in reversed_result.levels[0].groups}

    assert set(groups) == {"Alternatives", "Equity", "Real Estate"}
    assert set(reversed_groups) == set(groups)
    assert result.status == "partial"
    assert set(result.reason_codes) >= {"off_benchmark_exposure", "benchmark_only_exposure"}
    assert result.supportability_evidence.portfolio_only_group_count == 1
    assert result.supportability_evidence.benchmark_only_group_count == 1
    assert result.reconciliation.residual == pytest.approx(0.0, abs=1e-12)
    assert result.reconciliation.total_active_return == pytest.approx(0.6, abs=1e-12)
    for sector, group in groups.items():
        assert group.total_effect == pytest.approx(reversed_groups[sector].total_effect, abs=1e-12)


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


def test_prepare_data_from_instruments_preserves_unclassified_weight():
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
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1015}],
        },
        "instruments_data": [
            {
                "instrument_id": "CLASSIFIED",
                "meta": {"sector": "Tech"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612}],
            },
            {
                "instrument_id": "UNCLASSIFIED",
                "meta": {},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 403}],
            },
        ],
        "benchmark_groups_data": [],
    }
    request = AttributionRequest.model_validate(request_data)

    result_groups = _prepare_data_from_instruments(request)
    weights_by_sector = {group.key["sector"]: group.observations[0]["weight_bop"] for group in result_groups}

    assert weights_by_sector == pytest.approx({"Tech": 0.6, "unknown": 0.4})


def test_build_instrument_attribution_panel_uses_base_weight_points():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTR_BASE_WEIGHT",
            "mode": "by_instrument",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
            "instruments_data": [
                {
                    "instrument_id": "AAPL",
                    "meta": {
                        "sector": "Tech",
                        "base_weight_points": [
                            {"perf_date": "2025-01-01", "begin_mv": 250, "bod_cf": 50},
                        ],
                    },
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 900, "end_mv": 909}],
                }
            ],
            "benchmark_groups_data": [],
        }
    )

    panel = _build_instrument_attribution_panel(
        inst=request.instruments_data[0],
        request=request,
        twr_config=_build_test_twr_config(request),
        portfolio_bop_mv=pd.Series([1000.0], index=[pd.Timestamp("2025-01-01")]),
    )

    assert panel is not None
    row = panel.iloc[0]
    assert row["weight_bop"] == pytest.approx(0.3)
    assert row["return_base"] == pytest.approx(0.01)
    assert row["sector"] == "Tech"


def test_build_instrument_attribution_panel_backfills_same_currency_returns():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTR_SAME_CCY_PANEL",
            "mode": "by_instrument",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "currency_mode": "BOTH",
            "report_ccy": "USD",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
            "instruments_data": [
                {
                    "instrument_id": "AAPL",
                    "meta": {"sector": "Tech", "currency": "USD"},
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                }
            ],
            "benchmark_groups_data": [],
        }
    )

    panel = _build_instrument_attribution_panel(
        inst=request.instruments_data[0],
        request=request,
        twr_config=_build_test_twr_config(request),
        portfolio_bop_mv=pd.Series([1000.0], index=[pd.Timestamp("2025-01-01")]),
    )

    assert panel is not None
    row = panel.iloc[0]
    assert row["return_local"] == pytest.approx(row["return_base"])
    assert row["return_fx"] == pytest.approx(0.0)


def test_normalize_instrument_return_columns_backfills_and_scales_same_currency_returns():
    instrument_results = pd.DataFrame({"daily_ror": [2.5]})

    _normalize_instrument_return_columns(
        instrument_results,
        currency_mode="BOTH",
        instrument_currency="USD",
        report_ccy="USD",
    )

    assert instrument_results.to_dict(orient="records") == [
        {
            "return_base": 0.025,
            "return_local": 0.025,
            "return_fx": 0.0,
        }
    ]


def test_normalize_instrument_group_columns_adds_missing_group_keys():
    full_df = pd.DataFrame({"weight_bop": [1.0]})

    _normalize_instrument_group_columns(full_df, ["sector"])

    assert full_df["sector"].tolist() == ["unknown"]


def test_normalize_instrument_group_columns_replaces_blank_and_null_group_keys():
    full_df = pd.DataFrame({"sector": ["Tech", "", None]})

    _normalize_instrument_group_columns(full_df, ["sector"])

    assert full_df["sector"].tolist() == ["Tech", "unknown", "unknown"]


def test_prepare_panel_from_groups_handles_empty_cases():
    assert _prepare_panel_from_groups([], ["sector"]).empty

    class _EmptyGroup:
        key = {"sector": "Tech"}
        observations = []

    assert _prepare_panel_from_groups([_EmptyGroup()], ["sector"]).empty


def test_attribution_group_context_helpers_cover_empty_and_scalar_group_keys():
    assert _build_group_key_dict("Tech", ["sector"]) == {"sector": "Tech"}
    empty_context = _calculate_group_context_metrics(pd.DataFrame(), ["sector"])
    assert list(empty_context.columns) == [
        "portfolio_weight_avg",
        "benchmark_weight_avg",
        "portfolio_return",
        "benchmark_return",
    ]


def test_prepare_data_from_instruments_populates_same_currency_local_and_fx_columns():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTR_SAME_CCY",
            "mode": "by_instrument",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "currency_mode": "BOTH",
            "report_ccy": "USD",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
            "instruments_data": [
                {
                    "instrument_id": "AAPL",
                    "meta": {"sector": "", "currency": "USD"},
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                }
            ],
            "benchmark_groups_data": [],
        }
    )

    result_groups = _prepare_data_from_instruments(request)

    assert len(result_groups) == 1
    observation = result_groups[0].observations[0]
    assert result_groups[0].key == {"sector": "unknown"}
    assert observation["return_local"] == pytest.approx(observation["return_base"])
    assert observation["return_fx"] == pytest.approx(0.0)


def test_align_and_prepare_data_returns_empty_when_benchmark_missing(by_group_request_data):
    request_payload = by_group_request_data.copy()
    request_payload["benchmark_groups_data"] = []
    request = AttributionRequest.model_validate(request_payload)
    aligned_df = _align_and_prepare_data(request, request.portfolio_groups_data)
    assert aligned_df.empty


def test_align_and_prepare_data_uses_period_start_weights_for_sparse_groups():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "SPARSE_MONTHLY_ATTRIBUTION",
            "mode": "by_group",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "monthly",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
            "portfolio_groups_data": [
                {
                    "key": {"sector": "existing"},
                    "observations": [
                        {"date": "2025-01-01", "weight_bop": 1.0, "return_base": 0.01},
                        {"date": "2025-01-31", "weight_bop": 0.8, "return_base": 0.01},
                    ],
                },
                {
                    "key": {"sector": "acquired_mid_period"},
                    "observations": [
                        {"date": "2025-01-15", "weight_bop": 0.2, "return_base": 0.02},
                        {"date": "2025-01-31", "weight_bop": 0.2, "return_base": 0.02},
                    ],
                },
            ],
            "benchmark_groups_data": [
                {
                    "key": {"sector": "existing"},
                    "observations": [{"date": "2025-01-01", "weight_bop": 1.0, "return_base": 0.01}],
                },
                {
                    "key": {"sector": "acquired_mid_period"},
                    "observations": [{"date": "2025-01-01", "weight_bop": 0.0, "return_base": 0.0}],
                },
            ],
        }
    )

    aligned_df = _align_and_prepare_data(request, request.portfolio_groups_data or [])

    period_date = pd.Timestamp("2025-01-31")
    assert aligned_df.loc[(period_date, "existing"), "w_p"] == pytest.approx(1.0)
    assert aligned_df.loc[(period_date, "acquired_mid_period"), "w_p"] == pytest.approx(0.0)
    assert aligned_df.groupby(level="date")["w_p"].sum().loc[period_date] == pytest.approx(1.0)


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


def test_currency_attribution_totals_are_invariant_to_extra_grouping_dimensions():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTR_CCY_TOTALS_GRANULAR",
            "mode": "by_group",
            "group_by": ["currency", "sector"],
            "linking": "none",
            "frequency": "daily",
            "currency_mode": "BOTH",
            "report_ccy": "USD",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_groups_data": [
                {
                    "key": {"currency": "EUR", "sector": "Equity"},
                    "observations": [
                        {
                            "date": "2025-01-01",
                            "return_base": 0.041,
                            "return_local": 0.030,
                            "return_fx": 0.011,
                            "weight_bop": 0.30,
                        }
                    ],
                },
                {
                    "key": {"currency": "EUR", "sector": "Bonds"},
                    "observations": [
                        {
                            "date": "2025-01-01",
                            "return_base": 0.026,
                            "return_local": 0.015,
                            "return_fx": 0.011,
                            "weight_bop": 0.20,
                        }
                    ],
                },
            ],
            "benchmark_groups_data": [
                {
                    "key": {"currency": "EUR", "sector": "Equity"},
                    "observations": [
                        {
                            "date": "2025-01-01",
                            "return_base": 0.031,
                            "return_local": 0.020,
                            "return_fx": 0.011,
                            "weight_bop": 0.25,
                        }
                    ],
                },
                {
                    "key": {"currency": "EUR", "sector": "Bonds"},
                    "observations": [
                        {
                            "date": "2025-01-01",
                            "return_base": 0.051,
                            "return_local": 0.040,
                            "return_fx": 0.011,
                            "weight_bop": 0.25,
                        }
                    ],
                },
            ],
        }
    )

    effects_df, _ = run_attribution_calculations(request)
    result, lineage = aggregate_attribution_results(effects_df, request)

    totals = result.currency_attribution_totals
    assert totals is not None
    assert totals.currency_count == 1
    assert result.supportability_evidence.currency_attribution_status == "complete"
    assert "currency_attribution_effects.csv" in lineage

    # Currency-level returns are weight-averaged before Karnosky-Singer formulas are applied.
    expected_portfolio_local_return = ((0.30 * 0.030) + (0.20 * 0.015)) / 0.50
    expected_benchmark_local_return = ((0.25 * 0.020) + (0.25 * 0.040)) / 0.50
    expected_benchmark_fx_return = ((0.25 * 0.011) + (0.25 * 0.011)) / 0.50
    expected_local_allocation = (0.50 - 0.50) * expected_benchmark_local_return
    expected_local_selection = 0.50 * (expected_portfolio_local_return - expected_benchmark_local_return)
    expected_currency_allocation = (0.50 - 0.50) * (1 + expected_benchmark_local_return) * expected_benchmark_fx_return
    expected_currency_selection = (
        0.50 * (expected_portfolio_local_return - expected_benchmark_local_return) * expected_benchmark_fx_return
    )
    expected_total_effect = (
        expected_local_allocation
        + expected_local_selection
        + expected_currency_allocation
        + expected_currency_selection
    )

    assert totals.local_allocation == pytest.approx(expected_local_allocation * 100)
    assert totals.local_selection == pytest.approx(expected_local_selection * 100)
    assert totals.currency_allocation == pytest.approx(expected_currency_allocation * 100)
    assert totals.currency_selection == pytest.approx(expected_currency_selection * 100)
    assert totals.total_effect == pytest.approx(expected_total_effect * 100)


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


def test_residual_materiality_policy_classifies_review_and_material_breaks():
    immaterial = classify_attribution_residual(0.00009)
    watch = classify_attribution_residual(0.005)
    material = classify_attribution_residual(0.02)

    assert immaterial.classification == "immaterial"
    assert immaterial.treatment == "no_action"
    assert watch.classification == "watch"
    assert watch.treatment == "review"
    assert material.classification == "material"
    assert material.treatment == "investigate"


def test_attribution_supportability_evidence_flags_alignment_and_source_quality_edges():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTR_EDGE_STATUS",
            "mode": "by_group",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_groups_data": [
                {
                    "key": {"sector": "Tech"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.6}],
                },
                {
                    "key": {"sector": "Private Equity"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.2}],
                },
                {
                    "key": {"sector": "unknown"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.00, "weight_bop": 0.2}],
                },
                {
                    "key": {"sector": "Short Book"},
                    "observations": [{"date": "2025-01-01", "return_base": -0.01, "weight_bop": -0.1}],
                },
            ],
            "benchmark_groups_data": [
                {
                    "key": {"sector": "Tech"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.5}],
                },
                {
                    "key": {"sector": "Benchmark Only"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.005, "weight_bop": 0.2}],
                },
                {
                    "key": {"sector": "Health"},
                    "observations": [{"date": "2025-01-01", "weight_bop": 0.3}],
                },
            ],
        }
    )

    effects_df, _ = run_attribution_calculations(request)
    result, lineage = aggregate_attribution_results(effects_df, request)

    assert result.status == "partial"
    assert set(result.reason_codes) >= {
        "off_benchmark_exposure",
        "benchmark_only_exposure",
        "unclassified_segment",
        "missing_benchmark_return",
        "negative_weight",
    }
    assert result.supportability_evidence.portfolio_only_group_count == 3
    assert result.supportability_evidence.benchmark_only_group_count == 2
    assert result.supportability_evidence.unclassified_group_count == 1
    assert result.supportability_evidence.missing_benchmark_return_count == 1
    assert result.supportability_evidence.negative_weight_count == 1
    assert result.supportability_evidence.currency_attribution_status == "not_requested"
    assert result.supportability_evidence.linking_status == "not_requested"
    assert "attribution_supportability_evidence.csv" in lineage
    evidence_df = lineage["attribution_supportability_evidence.csv"]
    assert {"portfolio_only", "benchmark_only", "unclassified", "missing_benchmark_return"}.issubset(
        evidence_df.columns
    )


def test_attribution_supportability_evidence_flags_currency_and_linking_gaps():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTR_LINKING_STATUS",
            "mode": "by_group",
            "group_by": ["currency"],
            "linking": "carino",
            "frequency": "daily",
            "currency_mode": "BOTH",
            "report_ccy": "USD",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_groups_data": [
                {
                    "key": {"currency": "USD"},
                    "observations": [
                        {"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0},
                        {"date": "2025-01-02", "return_base": -0.01, "weight_bop": 1.0},
                    ],
                }
            ],
            "benchmark_groups_data": [
                {
                    "key": {"currency": "USD"},
                    "observations": [
                        {"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0},
                        {"date": "2025-01-02", "return_base": -0.01, "weight_bop": 1.0},
                    ],
                }
            ],
        }
    )

    effects_df, _ = run_attribution_calculations(request)
    result, _ = aggregate_attribution_results(effects_df, request)

    assert result.status == "partial"
    assert "currency_attribution_unavailable" in result.reason_codes
    assert "linking_scaling_skipped" in result.reason_codes
    assert result.supportability_evidence.currency_attribution_status == "unavailable"
    assert result.supportability_evidence.linking_status == "scaling_skipped"


def test_currency_attribution_fails_closed_when_currency_grouping_is_absent():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTR_CCY_GROUP_REQUIRED",
            "mode": "by_group",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "currency_mode": "BOTH",
            "report_ccy": "USD",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_groups_data": [
                {
                    "key": {"sector": "Global Equity"},
                    "observations": [
                        {
                            "date": "2025-01-01",
                            "return_base": 0.031,
                            "return_local": 0.025,
                            "return_fx": 0.006,
                            "weight_bop": 0.55,
                        }
                    ],
                }
            ],
            "benchmark_groups_data": [
                {
                    "key": {"sector": "Global Equity"},
                    "observations": [
                        {
                            "date": "2025-01-01",
                            "return_base": 0.029,
                            "return_local": 0.020,
                            "return_fx": 0.009,
                            "weight_bop": 0.50,
                        }
                    ],
                }
            ],
        }
    )

    effects_df, _ = run_attribution_calculations(request)
    result, lineage = aggregate_attribution_results(effects_df, request)

    assert result.status == "partial"
    assert "currency_attribution_unavailable" in result.reason_codes
    assert result.supportability_evidence.currency_attribution_status == "unavailable"
    assert result.currency_attribution is None
    assert result.currency_attribution_totals is None
    assert "currency_attribution_effects.csv" not in lineage


def test_attribution_linking_flags_invalid_return_chain_from_regression_pack():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTR_INVALID_LINKING_CHAIN",
            "mode": "by_group",
            "group_by": ["sector"],
            "linking": "carino",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_groups_data": [
                {
                    "key": {"sector": "Equity"},
                    "observations": [
                        {"date": "2025-01-01", "return_base": -1.0, "weight_bop": 1.0},
                        {"date": "2025-01-02", "return_base": 0.02, "weight_bop": 1.0},
                    ],
                }
            ],
            "benchmark_groups_data": [
                {
                    "key": {"sector": "Equity"},
                    "observations": [
                        {"date": "2025-01-01", "return_base": -0.90, "weight_bop": 1.0},
                        {"date": "2025-01-02", "return_base": 0.01, "weight_bop": 1.0},
                    ],
                }
            ],
        }
    )

    effects_df, _ = run_attribution_calculations(request)
    result, _ = aggregate_attribution_results(effects_df, request)

    assert result.status == "partial"
    assert "linking_invalid_return_chain" in result.reason_codes
    assert result.supportability_evidence.linking_status == "invalid_return_chain"
