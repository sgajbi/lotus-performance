from __future__ import annotations

from pathlib import Path

from scripts import demo_api_certification
from scripts.demo_api_certification import _cumulative_active_difference, _prepare_demo_runtime


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
