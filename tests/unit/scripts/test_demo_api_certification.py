from __future__ import annotations

from scripts.demo_api_certification import _cumulative_active_difference


def test_cumulative_active_difference_reconciles_portfolio_less_benchmark() -> None:
    assert (
        _cumulative_active_difference(
            ["0.010000000000", "0.005000000000", "-0.002500000000"],
            ["0.001000000000", "0.001200000000", "0.001400000000"],
        )
        == "0.008908093320"
    )
