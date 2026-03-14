# tests/unit/engine/test_engine_characterization.py
import pandas as pd
import pytest

from engine.compute import run_calculations
from tests.unit.engine.characterization_data import (
    CHARACTERIZATION_SCENARIOS,
)


@pytest.mark.parametrize(
    "scenario_func, scenario_name",
    [(scenario_func, scenario_name) for scenario_name, scenario_func in CHARACTERIZATION_SCENARIOS],
    ids=[scenario_name for scenario_name, _scenario_func in CHARACTERIZATION_SCENARIOS],
)
def test_engine_characterization_scenarios(scenario_func, scenario_name):
    """
    Characterization test for various scenarios, tied directly to the engine.
    """
    # 1. Arrange
    engine_config, input_df, expected_df = scenario_func()

    # 2. Act
    result_df, _ = run_calculations(input_df, engine_config)

    # 3. Assert
    output_columns = [col for col in expected_df.columns if col in result_df.columns]
    actual_df = result_df[output_columns].reset_index(drop=True)

    pd.testing.assert_frame_equal(
        actual_df,
        expected_df[output_columns].reset_index(drop=True),
        check_exact=False,
        atol=1e-4,
    )
