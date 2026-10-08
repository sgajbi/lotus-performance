"""SOD reset propagation preserves the scalar domain recurrence and engine results."""

from dataclasses import replace
from decimal import Decimal
from itertools import product

import numpy as np
import pandas as pd
import pytest

from engine import rules
from engine.compute import run_calculations
from engine.config import PrecisionMode
from tests.unit.engine.characterization_data import CHARACTERIZATION_SCENARIOS


def _scalar_sod_reset(next_open, canonical_reset, zero):
    result = np.zeros(len(canonical_reset), dtype=bool)
    for position in range(len(canonical_reset) - 2, -1, -1):
        result[position] = next_open[position] != zero and canonical_reset[position + 1]
        canonical_reset[position] |= result[position]
    return result


@pytest.mark.parametrize("length", range(7))
def test_sod_propagation_exhausts_opening_and_base_reset_states(length):
    """Include seeds at barriers, consecutive barriers and independent reset chains."""
    for state in product([False, True], repeat=2 * length):
        openings = np.array(state[:length], dtype=np.int64)
        actual_canonical = np.array(state[length:], dtype=bool)
        expected_canonical = actual_canonical.copy()
        expected = _scalar_sod_reset(openings, expected_canonical, 0)
        actual = rules._sod_reset_flags_from_next_open(openings, actual_canonical, 0)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(actual_canonical, expected_canonical)


@pytest.mark.parametrize("decimal_mode", [False, True])
def test_long_reset_chains_preserve_signed_fractional_and_zero_openings(decimal_mode):
    rng = np.random.default_rng(7321)
    openings = rng.choice([-3, 0, 2], size=10_000)
    if decimal_mode:
        openings = np.array([Decimal(int(value)) / Decimal(10) for value in openings], dtype=object)
    # Long uninterrupted chains on either side of a blocked opening.
    openings[:3000] = Decimal("-0.1") if decimal_mode else -1
    openings[3000] = 0
    openings[3001:6000] = Decimal("0.1") if decimal_mode else 1
    base = rng.choice([False, True], size=len(openings), p=[0.9, 0.1])
    base[2999] = base[5999] = True
    expected_canonical = base.copy()
    actual_canonical = base.copy()
    zero = Decimal(0) if decimal_mode else 0
    expected = _scalar_sod_reset(openings, expected_canonical, zero)
    actual = rules._sod_reset_flags_from_next_open(openings, actual_canonical, zero)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(actual_canonical, expected_canonical)


@pytest.mark.parametrize("scenario, name", [(scenario, name) for name, scenario in CHARACTERIZATION_SCENARIOS])
@pytest.mark.parametrize("mode", list(PrecisionMode))
def test_full_engine_frame_and_diagnostics_match_scalar_reset_rule(monkeypatch, scenario, name, mode):
    """Keep full monetary evidence, returns, reset reasons and reporting precision identical."""
    config, source, _ = scenario()
    config = replace(config, precision_mode=mode)
    original = source.copy(deep=True)
    actual_frame, actual_diagnostics = run_calculations(source, config)
    monkeypatch.setattr(rules, "_sod_reset_flags_from_next_open", _scalar_sod_reset)
    expected_frame, expected_diagnostics = run_calculations(source, config)
    pd.testing.assert_frame_equal(actual_frame, expected_frame, check_exact=True)
    assert actual_diagnostics == expected_diagnostics
    pd.testing.assert_frame_equal(source, original, check_exact=True)
