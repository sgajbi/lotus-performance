from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLATFORM_ROOT = REPO_ROOT.parent / "lotus-platform"
TELEMETRY_DIR = REPO_ROOT / "contracts" / "trust-telemetry"
SNAPSHOT_PATH = TELEMETRY_DIR / "returns-series-bundle.telemetry.v1.json"
TWR_SNAPSHOT_PATH = TELEMETRY_DIR / "time-weighted-return-analytics.telemetry.v1.json"
DECLARATION_PATH = REPO_ROOT / "contracts" / "domain-data-products" / "lotus-performance-products.v1.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_platform_validator():
    validator_path = PLATFORM_ROOT / "automation" / "validate_trust_telemetry.py"
    if not validator_path.exists():
        pytest.skip("lotus-platform trust telemetry validator is not available")
    automation_path = str(PLATFORM_ROOT / "automation")
    if automation_path not in sys.path:
        sys.path.insert(0, automation_path)
    return importlib.import_module("validate_trust_telemetry")


def test_returns_series_bundle_trust_telemetry_validates_with_platform_contract() -> None:
    validator = _load_platform_validator()

    issues = validator.validate_trust_telemetry_path(
        TELEMETRY_DIR,
        catalog_path=PLATFORM_ROOT / "generated" / "domain-product-catalog.json",
    )

    assert issues == []


def test_returns_series_bundle_trust_telemetry_is_tied_to_repo_declaration() -> None:
    snapshot = _load_json(SNAPSHOT_PATH)
    declaration = _load_json(DECLARATION_PATH)
    declared_product = next(
        product for product in declaration["products"] if product["product_name"] == "ReturnsSeriesBundle"
    )

    assert snapshot["product_id"] == "lotus-performance:ReturnsSeriesBundle:v1"
    assert snapshot["producer_repository"] == declaration["producer_repository"]
    assert snapshot["product_name"] == declared_product["product_name"]
    assert snapshot["product_version"] == declared_product["product_version"]
    assert snapshot["freshness"]["freshness_class"] == (declared_product["freshness_policy"]["freshness_class"])
    assert set(snapshot["observed_trust_metadata"]) == set(declared_product["required_trust_metadata"])
    assert snapshot["lineage"]["lineage_materialized"] is True
    assert (
        snapshot["lineage"]["evidence_access_class"]
        == (declared_product["lineage_policy"]["evidence_access_class_ref"])
    )
    assert snapshot["blocking"]["blocked"] is False


def test_time_weighted_return_analytics_trust_telemetry_is_tied_to_repo_declaration() -> None:
    snapshot = _load_json(TWR_SNAPSHOT_PATH)
    declaration = _load_json(DECLARATION_PATH)
    declared_product = next(
        product for product in declaration["products"] if product["product_name"] == "TimeWeightedReturnAnalytics"
    )

    assert snapshot["product_id"] == "lotus-performance:TimeWeightedReturnAnalytics:v1"
    assert snapshot["producer_repository"] == declaration["producer_repository"]
    assert snapshot["product_name"] == declared_product["product_name"]
    assert snapshot["product_version"] == declared_product["product_version"]
    assert snapshot["freshness"]["freshness_class"] == declared_product["freshness_policy"]["freshness_class"]
    assert set(snapshot["observed_trust_metadata"]) == set(declared_product["required_trust_metadata"])
    assert snapshot["lineage"]["lineage_materialized"] is True
    assert (
        snapshot["lineage"]["evidence_access_class"] == declared_product["lineage_policy"]["evidence_access_class_ref"]
    )
    assert snapshot["blocking"]["blocked"] is False
