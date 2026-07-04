import json

import pytest

from scripts.validate_domain_data_product_contracts import (
    LOCAL_DECLARATION_DIR,
    _collect_required_upstream_product_paths,
    _resolve_platform_root,
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


def test_platform_root_resolution_prefers_explicit_environment(monkeypatch, tmp_path) -> None:
    platform_root = tmp_path / "platform"
    (platform_root / "platform-contracts").mkdir(parents=True)

    monkeypatch.setenv("LOTUS_PLATFORM_ROOT", str(platform_root))

    assert _resolve_platform_root() == platform_root.resolve()


def test_platform_root_resolution_supports_nested_ci_checkout(monkeypatch, tmp_path) -> None:
    import scripts.validate_domain_data_product_contracts as validator

    repo_root = tmp_path / "lotus-performance"
    platform_root = repo_root / ".lotus-platform"
    (platform_root / "platform-contracts").mkdir(parents=True)

    monkeypatch.delenv("LOTUS_PLATFORM_ROOT", raising=False)
    monkeypatch.setattr(validator, "ROOT", repo_root)

    assert validator._resolve_platform_root() == platform_root.resolve()


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
        "MandatePerformanceHealthContext",
        "ReturnsSeriesBundle",
        "BenchmarkExposureContext",
        "CompositePerformanceAnalytics",
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
    assert "source_position_key" in contribution_product["identifier_refs"]
    attribution_product = payload["products"][3]
    assert attribution_product["approved_consumers"] == ["lotus-gateway"]
    assert attribution_product["current_routes"] == [
        "/performance/attribution",
        "/performance/attribution/results/{calculation_id}",
    ]
    assert "source_position_key" in attribution_product["identifier_refs"]
    assert "benchmark_context" in attribution_product["required_trust_metadata"]
    assert "reconciliation_status" in attribution_product["required_trust_metadata"]
    assert "coverage_status" in attribution_product["required_trust_metadata"]
    assert "coverage_ratio" in attribution_product["required_trust_metadata"]
    mandate_health_product = payload["products"][4]
    assert mandate_health_product["approved_consumers"] == [
        "lotus-gateway",
        "lotus-manage",
        "lotus-idea",
    ]
    assert mandate_health_product["current_routes"] == ["/performance/mandate-health-context"]
    assert mandate_health_product["completeness_policy"]["partial_allowed"] is True
    assert "request_fingerprint" in mandate_health_product["required_trust_metadata"]
    assert "source_services" in mandate_health_product["required_trust_metadata"]
    assert "benchmark_context" in mandate_health_product["required_trust_metadata"]
    assert "correlation_id" in mandate_health_product["required_trust_metadata"]
    assert payload["products"][5]["approved_consumers"] == ["lotus-risk", "lotus-idea"]
    assert "correlation_id" in payload["products"][5]["required_trust_metadata"]
    assert payload["products"][6]["approved_consumers"] == ["lotus-risk", "lotus-idea"]
    assert "correlation_id" in payload["products"][6]["required_trust_metadata"]
    composite_product = payload["products"][7]
    assert composite_product["approved_consumers"] == ["lotus-gateway"]
    assert composite_product["current_routes"] == ["/performance/composites/twr"]
    assert composite_product["request_scope"]["scope_level"] == "portfolio_set"
    assert composite_product["freshness_policy"]["freshness_class"] == "batch"
    assert "composite_id" in composite_product["identifier_refs"]
    assert "lineage_version" in composite_product["required_trust_metadata"]


def test_repo_native_consumer_declarations_include_active_upstream_dependencies() -> None:
    payload = _load_declaration("lotus-performance-consumers.v1.json")

    dependency_names = [dependency["product_name"] for dependency in payload["dependencies"]]
    dependencies_by_name = {dependency["product_name"]: dependency for dependency in payload["dependencies"]}

    assert payload["consumer_repository"] == "lotus-performance"
    assert dependency_names == [
        "PortfolioTimeseriesInput",
        "PositionTimeseriesInput",
        "PerformanceComponentEconomics",
        "PortfolioAnalyticsReference",
        "BenchmarkAssignment",
        "MarketDataWindow",
        "InstrumentReferenceBundle",
        "RiskFreeSeriesWindow",
        "BenchmarkConstituentWindow",
        "IndexSeriesWindow",
    ]
    for product_name in ("BenchmarkConstituentWindow", "IndexSeriesWindow"):
        dependency = dependencies_by_name[product_name]
        assert dependency["producer_repository"] == "lotus-core"
        assert dependency["required_product_version"] == "v1"
        assert dependency["failure_posture"] == "fail_closed"
        assert "source_batch_fingerprint" in dependency["required_trust_metadata"]
        assert "correlation_id" in dependency["required_trust_metadata"]


def test_portfolio_timeseries_consumer_documents_optional_mwr_lifecycle_identity_fields() -> None:
    payload = _load_declaration("lotus-performance-consumers.v1.json")
    portfolio_timeseries = payload["dependencies"][0]

    assert portfolio_timeseries["product_name"] == "PortfolioTimeseriesInput"
    assert "cash_flows[].source_transaction_id" in portfolio_timeseries["optional_source_fields"]
    assert "cash_flows[].source_event_id" in portfolio_timeseries["optional_source_fields"]
    assert "cash_flows[].reversal_reference_id" in portfolio_timeseries["optional_source_fields"]
    assert "cash_flows[].settlement_date" in portfolio_timeseries["optional_source_fields"]
    assert "not_supplied_by_source" in portfolio_timeseries["optional_source_field_posture"]
