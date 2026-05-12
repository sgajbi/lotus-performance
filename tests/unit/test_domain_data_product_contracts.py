import json

import pytest

from scripts.validate_domain_data_product_contracts import (
    LOCAL_DECLARATION_DIR,
    _collect_required_upstream_product_paths,
    platform_validation_dependencies_available,
    validate_repo_native_contracts,
)


def _load_declaration(name: str) -> dict:
    return json.loads((LOCAL_DECLARATION_DIR / name).read_text(encoding="utf-8"))


def test_repo_native_domain_data_product_validation_passes() -> None:
    if not platform_validation_dependencies_available():
        pytest.skip("lotus-platform validation dependencies are not available in this environment")

    assert validate_repo_native_contracts() == []


def test_repo_native_domain_data_product_directory_contains_expected_files() -> None:
    declaration_names = {path.name for path in LOCAL_DECLARATION_DIR.glob("*.json")}

    assert declaration_names == {
        "lotus-performance-products.v1.json",
        "lotus-performance-consumers.v1.json",
    }


def test_repo_native_declaration_readme_documents_local_validation_path() -> None:
    readme = (LOCAL_DECLARATION_DIR / "README.md").read_text(encoding="utf-8")

    assert "python scripts/validate_domain_data_product_contracts.py" in readme
    assert "make domain-product-validate" in readme
    assert "docs/technical/RFC-0082-upstream-contract-family-map.md" in readme


def test_repo_native_validation_script_stages_upstream_core_products() -> None:
    if not platform_validation_dependencies_available():
        pytest.skip("lotus-platform validation dependencies are not available in this environment")

    upstream_paths = _collect_required_upstream_product_paths(LOCAL_DECLARATION_DIR)

    assert [path.name for path in upstream_paths] == ["lotus-core-products.v1.json"]


def test_repo_native_producer_declarations_cover_governed_first_wave_products_and_twr_mwr() -> None:
    payload = _load_declaration("lotus-performance-products.v1.json")

    assert payload["producer_repository"] == "lotus-performance"
    assert [product["product_name"] for product in payload["products"]] == [
        "TimeWeightedReturnAnalytics",
        "MoneyWeightedReturnAnalytics",
        "ContributionAnalytics",
        "AttributionAnalytics",
        "ReturnsSeriesBundle",
        "BenchmarkExposureContext",
    ]
    twr_product = payload["products"][0]
    assert twr_product["approved_consumers"] == ["lotus-gateway"]
    assert twr_product["current_routes"] == ["/performance/twr", "/performance/twr/results/{calculation_id}"]
    assert "upstream_request_fingerprints" in twr_product["required_trust_metadata"]
    assert twr_product["lineage_policy"]["lineage_required"] is True
    assert payload["products"][1]["approved_consumers"] == ["lotus-gateway"]
    assert payload["products"][1]["current_routes"] == ["/performance/mwr"]
    assert "upstream_request_fingerprints" in payload["products"][1]["required_trust_metadata"]
    contribution_product = payload["products"][2]
    assert contribution_product["approved_consumers"] == ["lotus-gateway"]
    assert contribution_product["current_routes"] == [
        "/performance/contribution",
        "/performance/contribution/results/{calculation_id}",
    ]
    assert "coverage_status" in contribution_product["required_trust_metadata"]
    assert "coverage_ratio" in contribution_product["required_trust_metadata"]
    attribution_product = payload["products"][3]
    assert attribution_product["approved_consumers"] == ["lotus-gateway"]
    assert attribution_product["current_routes"] == [
        "/performance/attribution",
        "/performance/attribution/results/{calculation_id}",
    ]
    assert "benchmark_context" in attribution_product["required_trust_metadata"]
    assert "reconciliation_status" in attribution_product["required_trust_metadata"]
    assert "coverage_status" in attribution_product["required_trust_metadata"]
    assert "coverage_ratio" in attribution_product["required_trust_metadata"]
    assert payload["products"][4]["approved_consumers"] == ["lotus-risk"]
    assert payload["products"][5]["approved_consumers"] == ["lotus-risk"]


def test_repo_native_consumer_declarations_keep_watchlist_dependencies_docs_only() -> None:
    payload = _load_declaration("lotus-performance-consumers.v1.json")

    dependency_names = [dependency["product_name"] for dependency in payload["dependencies"]]

    assert payload["consumer_repository"] == "lotus-performance"
    assert dependency_names == [
        "PortfolioTimeseriesInput",
        "PositionTimeseriesInput",
        "PortfolioAnalyticsReference",
        "BenchmarkAssignment",
        "MarketDataWindow",
        "InstrumentReferenceBundle",
        "RiskFreeSeriesWindow",
    ]
