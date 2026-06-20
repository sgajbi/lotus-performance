from __future__ import annotations

from scripts.demo_api_certification import certify_demo_apis


def test_demo_api_certification_calls_supported_demo_feature_apis() -> None:
    report = certify_demo_apis()

    assert report["status"] == "passed"
    assert report["api_call_count"] == 13
    assert set(report["feature_families"]) == {
        "capabilities",
        "twr",
        "mwr",
        "benchmark",
        "returns_series",
        "contribution",
        "attribution",
        "workspace_summary",
        "mandate_health_context",
        "composite_twr",
    }
    check_names = {check["name"] for check in report["checks"]}
    assert check_names == {
        "capability_registry",
        "twr_contribution_attribution_story",
        "mwr_xirr",
        "benchmark_calculated",
        "returns_series",
        "workspace_summary",
        "mandate_health_context",
        "composite_twr",
    }
