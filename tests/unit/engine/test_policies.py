import pandas as pd
import pytest

from app.models.requests import DataPolicy
from engine.diagnostics import EngineDiagnostics
from engine.policies import _extract_policy_inputs, _flag_outliers, apply_robustness_policies
from engine.schema import PortfolioColumns


@pytest.fixture
def sample_policy_df():
    """Provides a sample DataFrame for policy tests."""
    return pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: pd.to_datetime(["2025-03-14", "2025-03-15", "2025-03-16"]),
            "position_id": ["P1", "P1", "P1"],
            PortfolioColumns.BEGIN_MV.value: [100.0, 110.0, 120.0],
            PortfolioColumns.END_MV.value: [110.0, 120.0, 130.0],
            PortfolioColumns.BOD_CF.value: [0.0, 5.0, 0.0],
            PortfolioColumns.EOD_CF.value: [0.0, 0.0, 0.0],
            PortfolioColumns.MGMT_FEES.value: [0.0, 0.0, 0.0],
        }
    )


def test_apply_overrides_market_value(sample_policy_df):
    """Tests that a market value override is correctly applied."""
    policy = DataPolicy.model_validate(
        {"overrides": {"market_values": [{"perf_date": "2025-03-15", "position_id": "P1", "end_mv": 999.0}]}}
    )
    result_df, diags = apply_robustness_policies(sample_policy_df, policy)
    assert result_df.loc[1, PortfolioColumns.END_MV.value] == 999.0
    assert diags.policy.overrides.applied_mv_count == 1


def test_apply_overrides_cash_flow(sample_policy_df):
    """Tests that a cash flow override is correctly applied."""
    policy = DataPolicy.model_validate({"overrides": {"cash_flows": [{"perf_date": "2025-03-15", "bod_cf": -50.0}]}})
    result_df, diags = apply_robustness_policies(sample_policy_df, policy)
    assert result_df.loc[1, PortfolioColumns.BOD_CF.value] == -50.0
    assert diags.policy.overrides.applied_cf_count == 1


def test_apply_ignore_days(sample_policy_df):
    """Tests that an ignored day carries forward the previous day's state."""
    policy = DataPolicy.model_validate(
        {"ignore_days": [{"entity_type": "POSITION", "entity_id": "P1", "dates": ["2025-03-15"]}]}
    )
    result_df, diags = apply_robustness_policies(sample_policy_df, policy)
    assert result_df.loc[1, PortfolioColumns.BEGIN_MV.value] == 110.0
    assert result_df.loc[1, PortfolioColumns.END_MV.value] == 110.0
    assert result_df.loc[1, PortfolioColumns.BOD_CF.value] == 0.0
    assert diags.policy.ignored_days_count == 1


def test_apply_robustness_policies_preserves_original_df_when_mutating(sample_policy_df):
    original_df = sample_policy_df.copy(deep=True)
    policy = DataPolicy.model_validate(
        {
            "overrides": {"market_values": [{"perf_date": "2025-03-15", "position_id": "P1", "end_mv": 999.0}]},
            "ignore_days": [{"entity_type": "POSITION", "entity_id": "P1", "dates": ["2025-03-16"]}],
        }
    )

    result_df, diags = apply_robustness_policies(sample_policy_df, policy)

    pd.testing.assert_frame_equal(sample_policy_df, original_df)
    assert result_df.loc[1, PortfolioColumns.END_MV.value] == 999.0
    assert result_df.loc[2, PortfolioColumns.BEGIN_MV.value] == 999.0
    assert diags.policy.overrides.applied_mv_count == 1
    assert diags.policy.ignored_days_count == 1


def test_flag_outliers():
    """Tests that the outlier flagging function correctly identifies outliers but does not change data."""
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE.value: pd.to_datetime(pd.date_range(start="2025-01-01", periods=10)),
            PortfolioColumns.DAILY_ROR.value: [1.0, 1.1, 0.9, 1.2, 0.8, 99.0, 1.0, 1.1, 0.9, 1.0],
        }
    )
    policy_model = DataPolicy.model_validate(
        {"outliers": {"enabled": True, "action": "FLAG", "params": {"window": 5, "mad_k": 3.0}}}
    )
    diagnostics = EngineDiagnostics()
    _flag_outliers(df, policy_model, diagnostics, ignored_dates=_extract_policy_inputs(policy_model).ignored_dates)
    assert diagnostics.policy.outliers.flagged_rows == 1
    assert diagnostics.samples.outliers[0].raw_return == 99.0
    assert df.loc[5, PortfolioColumns.DAILY_ROR.value] == 99.0


def test_no_policy_does_nothing(sample_policy_df):
    """Tests that if no policy is provided, the DataFrame and diagnostics are unchanged."""
    original_df = sample_policy_df.copy()
    result_df, diags = apply_robustness_policies(sample_policy_df, None)
    pd.testing.assert_frame_equal(original_df, result_df)
    assert diags.policy.overrides.applied_mv_count == 0
    assert diags.policy.ignored_days_count == 0


def test_flag_outliers_returns_early_when_disabled(sample_policy_df):
    diagnostics = EngineDiagnostics()
    policy_model = DataPolicy.model_validate({"outliers": {"enabled": False}})
    _flag_outliers(
        sample_policy_df.copy(),
        policy_model,
        diagnostics,
        ignored_dates=_extract_policy_inputs(policy_model).ignored_dates,
    )
    assert diagnostics.policy.outliers.flagged_rows == 0


def test_flag_outliers_returns_early_for_non_flag_action(sample_policy_df):
    diagnostics = EngineDiagnostics()

    class _Outliers:
        enabled = True

        @staticmethod
        def model_dump():
            return {"action": "IGNORE", "params": {}}

    class _Policy:
        outliers = _Outliers()
        ignore_days = None

    policy_model = _Policy()
    _flag_outliers(sample_policy_df.copy(), policy_model, diagnostics, ignored_dates=set())
    assert diagnostics.policy.outliers.flagged_rows == 0


def test_flag_outliers_returns_early_when_daily_ror_missing(sample_policy_df):
    diagnostics = EngineDiagnostics()
    policy_model = DataPolicy.model_validate({"outliers": {"enabled": True, "action": "FLAG"}})
    df_without_ror = sample_policy_df.drop(columns=[PortfolioColumns.END_MV.value]).copy()
    _flag_outliers(
        df_without_ror,
        policy_model,
        diagnostics,
        ignored_dates=_extract_policy_inputs(policy_model).ignored_dates,
    )
    assert diagnostics.policy.outliers.flagged_rows == 0


def test_extract_policy_inputs_collects_ignored_dates():
    policy = DataPolicy.model_validate(
        {
            "ignore_days": [
                {"entity_type": "POSITION", "entity_id": "P1", "dates": ["2025-03-15", "2025-03-16"]},
                {"entity_type": "POSITION", "entity_id": "P2", "dates": ["2025-03-16"]},
            ]
        }
    )

    inputs = _extract_policy_inputs(policy)

    assert inputs.ignored_dates == {
        pd.Timestamp("2025-03-15").date(),
        pd.Timestamp("2025-03-16").date(),
    }
