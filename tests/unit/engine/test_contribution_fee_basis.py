from decimal import Decimal

import pandas as pd
import pytest

from app.models.contribution_requests import ContributionRequest
from core.envelope import DataPolicy
from engine.config import EndingValueBasis, EngineConfig, PrecisionMode
from engine.contribution import _prepare_hierarchical_data, _retain_zero_capital_contribution
from engine.contribution_fee_basis import normalize_after_fee_ending_values
from engine.runtime import run_engine_for_valuation_points
from engine.schema import PortfolioColumns


@pytest.mark.parametrize("decimal_mode", [False, True])
def test_zero_capital_allocation_preserves_funded_rows_and_zero_portfolio_guard(decimal_mode):
    number = Decimal if decimal_mode else float
    frame = pd.DataFrame(
        {
            "capital_inst": [number(0), number(100), number(0)],
            "capital_port": [number(1000), number(1000), number(0)],
            "_contribution_local_pnl": [number(-10), number(99), number(-10)],
            "_contribution_base_pnl": [number(-12), number(99), number(-12)],
            "raw_local_contribution": [number(0), number("0.05"), number(0)],
            "raw_contribution": [number(0), number("0.06"), number(0)],
            "raw_fx_contribution": [number(0), number("0.01"), number(0)],
        }
    )

    _retain_zero_capital_contribution(frame, decimal_mode=decimal_mode)

    assert frame["raw_contribution"].tolist() == [number("-0.012"), number("0.06"), number(0)]
    assert frame["raw_local_contribution"].tolist() == [number("-0.01"), number("0.05"), number(0)]
    assert float(frame["raw_fx_contribution"].iloc[0]) == pytest.approx(-0.002)
    assert frame["raw_fx_contribution"].iloc[1] == number("0.01")
    if decimal_mode:
        assert all(isinstance(value, Decimal) for value in frame["raw_contribution"])


def test_contribution_points_reconstruct_fee_exclusive_end_values_in_strict_decimal_mode():
    frame = pd.DataFrame(
        [
            {"end_mv": Decimal("1090"), "mgmt_fees": Decimal("-10")},
            {"end_mv": Decimal("1110"), "mgmt_fees": Decimal("10")},
            {"end_mv": Decimal("1100"), "mgmt_fees": Decimal("0")},
            {"end_mv": 1090.1, "mgmt_fees": -0.1},
        ]
    )

    normalize_after_fee_ending_values(frame, PrecisionMode.DECIMAL_STRICT)

    assert frame["end_mv"].tolist() == [
        Decimal("1100"),
        Decimal("1100"),
        Decimal("1100"),
        Decimal("1090.2"),
    ]

    override_result = run_engine_for_valuation_points(
        [
            {
                "perf_date": "2025-01-01",
                "begin_mv": Decimal("1000"),
                "end_mv": Decimal("1090"),
            }
        ],
        EngineConfig(
            performance_start_date=pd.Timestamp("2025-01-01").date(),
            report_start_date=pd.Timestamp("2025-01-01").date(),
            report_end_date=pd.Timestamp("2025-01-01").date(),
            period_type="EXPLICIT",
            metric_basis="NET",
            precision_mode=PrecisionMode.DECIMAL_STRICT,
            data_policy=DataPolicy.model_validate(
                {
                    "overrides": {
                        "market_values": [{"perf_date": "2025-01-01", "begin_mv": 1000.1, "end_mv": 1090.3}],
                        "cash_flows": [{"perf_date": "2025-01-01", "bod_cf": 0.2, "eod_cf": 0.1}],
                    }
                }
            ),
        ),
    )
    expected_override_return = Decimal("89.9") / Decimal("1000.3") * Decimal("100")
    assert override_result[PortfolioColumns.DAILY_ROR.value].iloc[0] == expected_override_return

    ignored_result = run_engine_for_valuation_points(
        [
            {"perf_date": "2025-01-01", "begin_mv": Decimal("1000.1"), "end_mv": Decimal("1000.1")},
            {"perf_date": "2025-01-02", "begin_mv": Decimal("1000.1"), "end_mv": Decimal("1100.1")},
        ],
        EngineConfig(
            performance_start_date=pd.Timestamp("2025-01-01").date(),
            report_start_date=pd.Timestamp("2025-01-01").date(),
            report_end_date=pd.Timestamp("2025-01-02").date(),
            period_type="EXPLICIT",
            metric_basis="NET",
            precision_mode=PrecisionMode.DECIMAL_STRICT,
            data_policy=DataPolicy.model_validate(
                {"ignore_days": [{"entity_type": "PORTFOLIO", "entity_id": "P1", "dates": ["2025-01-02"]}]}
            ),
        ),
    )
    assert ignored_result[PortfolioColumns.DAILY_ROR.value].iloc[-1] == Decimal("0")


@pytest.mark.parametrize(
    ("metric_basis", "end_mv", "management_fees", "expected_return"),
    [
        ("NET", Decimal("1090"), Decimal("-10"), Decimal("9.00")),
        ("GROSS", Decimal("1090"), Decimal("-10"), Decimal("10.0")),
        ("NET", Decimal("1110"), Decimal("10"), Decimal("11.00")),
        ("GROSS", Decimal("1110"), Decimal("10"), Decimal("10.0")),
    ],
)
def test_contribution_fee_basis_produces_independent_net_and_gross_returns(
    metric_basis,
    end_mv,
    management_fees,
    expected_return,
):
    points = [
        {
            "perf_date": "2025-01-01",
            "begin_mv": Decimal("1000"),
            "end_mv": end_mv,
            "mgmt_fees": management_fees,
        }
    ]
    result = run_engine_for_valuation_points(
        points,
        EngineConfig(
            performance_start_date=pd.Timestamp("2025-01-01").date(),
            report_start_date=pd.Timestamp("2025-01-01").date(),
            report_end_date=pd.Timestamp("2025-01-01").date(),
            period_type="EXPLICIT",
            metric_basis=metric_basis,
            precision_mode=PrecisionMode.DECIMAL_STRICT,
            ending_value_basis=EndingValueBasis.AFTER_FEES,
        ),
    )

    assert result[PortfolioColumns.DAILY_ROR.value].iloc[0] == expected_return


@pytest.mark.parametrize(
    ("metric_basis", "end_mv", "management_fees", "precision_mode", "expected_return"),
    [
        ("NET", 1090, -10, "FLOAT64", 9.0),
        ("GROSS", 1090, -10, "FLOAT64", 10.0),
        ("NET", 1090.1, -0.1, "DECIMAL_STRICT", Decimal("9.0100")),
    ],
)
def test_contribution_engine_boundary_normalizes_portfolio_and_position_rows(
    metric_basis,
    end_mv,
    management_fees,
    precision_mode,
    expected_return,
):
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": f"FEE_BASIS_{metric_basis}",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "precision_mode": precision_mode,
            "portfolio_data": {
                "metric_basis": metric_basis,
                "valuation_points": [
                    {
                        "perf_date": "2025-01-01",
                        "begin_mv": 1000,
                        "end_mv": end_mv,
                        "mgmt_fees": management_fees,
                    }
                ],
            },
            "positions_data": [
                {
                    "position_id": "USD_ASSET",
                    "valuation_points": [
                        {
                            "perf_date": "2025-01-01",
                            "begin_mv": 1000,
                            "end_mv": end_mv,
                            "mgmt_fees": management_fees,
                        }
                    ],
                }
            ],
        }
    )

    position_results, portfolio_results = _prepare_hierarchical_data(request)

    if precision_mode == "DECIMAL_STRICT":
        assert portfolio_results[PortfolioColumns.DAILY_ROR.value].iloc[0] == expected_return
        assert position_results[PortfolioColumns.DAILY_ROR.value].iloc[0] == expected_return
    else:
        assert portfolio_results[PortfolioColumns.DAILY_ROR.value].iloc[0] == pytest.approx(expected_return)
        assert position_results[PortfolioColumns.DAILY_ROR.value].iloc[0] == pytest.approx(expected_return)


@pytest.mark.parametrize(
    ("metric_basis", "expected_portfolio_return", "expected_position_return"),
    [("NET", 8.0, 7.0), ("GROSS", 9.0, 8.0)],
)
def test_contribution_market_value_overrides_preserve_after_fee_basis_and_entity_scope(
    metric_basis,
    expected_portfolio_return,
    expected_position_return,
):
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "OVERRIDE_PORTFOLIO",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": metric_basis,
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1090, "mgmt_fees": -10}],
            },
            "positions_data": [
                {
                    "position_id": "USD_ASSET",
                    "valuation_points": [
                        {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1090, "mgmt_fees": -10}
                    ],
                }
            ],
            "data_policy": {
                "overrides": {
                    "market_values": [
                        {
                            "perf_date": "2025-01-01",
                            "portfolio_id": "OVERRIDE_PORTFOLIO",
                            "end_mv": 1080,
                        },
                        {"perf_date": "2025-01-01", "position_id": "USD_ASSET", "end_mv": 1070},
                    ]
                }
            },
        }
    )

    position_results, portfolio_results = _prepare_hierarchical_data(request)

    assert portfolio_results[PortfolioColumns.DAILY_ROR.value].iloc[0] == pytest.approx(expected_portfolio_return)
    assert position_results[PortfolioColumns.DAILY_ROR.value].iloc[0] == pytest.approx(expected_position_return)


def test_contribution_outlier_scope_and_samples_retain_entity_identity():
    outlier_returns = [1.0, 1.1, 0.9, 1.2, 0.8, 99.0, 1.0, 1.1, 0.9, 1.0]
    outlier_points = [
        {
            "perf_date": str(perf_date.date()),
            "begin_mv": 1000,
            "end_mv": 1000 * (1 + daily_return / 100),
        }
        for perf_date, daily_return in zip(pd.date_range("2025-01-01", periods=10), outlier_returns, strict=True)
    ]
    outlier_request = ContributionRequest.model_validate(
        {
            "portfolio_id": "OUTLIER_SCOPE_PORTFOLIO",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-10",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "portfolio_data": {"metric_basis": "NET", "valuation_points": outlier_points},
            "positions_data": [
                {"position_id": "OUTLIER_POSITION_1", "valuation_points": outlier_points},
                {"position_id": "OUTLIER_POSITION_2", "valuation_points": outlier_points},
            ],
            "data_policy": {"outliers": {"enabled": True, "action": "FLAG", "params": {"window": 5, "mad_k": 3.0}}},
        }
    )

    prepared_data = _prepare_hierarchical_data(outlier_request)
    portfolio_diagnostics, *position_diagnostics = prepared_data.engine_diagnostics

    assert portfolio_diagnostics.policy.outliers.flagged_rows == 0
    assert portfolio_diagnostics.samples.outliers == []
    assert [diagnostics.policy.outliers.flagged_rows for diagnostics in position_diagnostics] == [1, 1]
    assert [diagnostics.samples.outliers[0].entity_type for diagnostics in position_diagnostics] == [
        "POSITION",
        "POSITION",
    ]
    assert [diagnostics.samples.outliers[0].entity_id for diagnostics in position_diagnostics] == [
        "OUTLIER_POSITION_1",
        "OUTLIER_POSITION_2",
    ]

    portfolio_outlier_payload = outlier_request.model_dump(mode="json")
    portfolio_outlier_payload["data_policy"]["outliers"]["scope"] = [
        "SECURITY_RETURNS",
        "PORTFOLIO_RETURNS",
    ]
    portfolio_outlier_request = ContributionRequest.model_validate(portfolio_outlier_payload)
    portfolio_scoped_data = _prepare_hierarchical_data(portfolio_outlier_request)
    portfolio_scoped_diagnostics = portfolio_scoped_data.engine_diagnostics[0]

    assert portfolio_scoped_diagnostics.policy.outliers.flagged_rows == 1
    assert portfolio_scoped_diagnostics.samples.outliers[0].entity_type == "PORTFOLIO"
    assert portfolio_scoped_diagnostics.samples.outliers[0].entity_id == "OUTLIER_SCOPE_PORTFOLIO"
