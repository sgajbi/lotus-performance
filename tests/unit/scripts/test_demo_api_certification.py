from __future__ import annotations

from pathlib import Path

import pytest

from scripts import demo_api_certification
from scripts.demo_api_certification import (
    _assert_enabled_demo_surfaces,
    _cumulative_active_difference,
    _expected_demo_capability_paths,
    _prepare_demo_runtime,
)


def test_cumulative_active_difference_reconciles_portfolio_less_benchmark() -> None:
    assert (
        _cumulative_active_difference(
            ["0.010000000000", "0.005000000000", "-0.002500000000"],
            ["0.001000000000", "0.001200000000", "0.001400000000"],
        )
        == "0.008908093320"
    )


def test_prepare_demo_runtime_creates_lineage_storage_path(monkeypatch, tmp_path) -> None:
    lineage_storage_path = tmp_path / "lineage-data"
    calls: list[str] = []

    monkeypatch.setattr(
        demo_api_certification,
        "get_settings",
        lambda: type("Settings", (), {"LINEAGE_STORAGE_PATH": Path(lineage_storage_path)})(),
    )
    monkeypatch.setattr(demo_api_certification, "bootstrap_durable_metadata_stores", lambda: calls.append("bootstrap"))

    _prepare_demo_runtime()

    assert lineage_storage_path.is_dir()
    assert calls == ["bootstrap"]


def test_assert_enabled_demo_surfaces_rejects_disabled_expected_surface() -> None:
    expected_paths = _expected_demo_capability_paths()
    capabilities = {
        "analytics_surfaces": [
            {"path": path, "enabled": path != "/performance/composites/twr"} for path in sorted(expected_paths)
        ]
    }

    with pytest.raises(AssertionError) as exc_info:
        _assert_enabled_demo_surfaces(capabilities, expected_paths)

    assert "/performance/composites/twr" in str(exc_info.value)
