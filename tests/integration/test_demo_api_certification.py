from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from scripts.demo_api_certification import certify_demo_apis


def test_demo_api_certification_calls_supported_demo_feature_apis() -> None:
    previous = getattr(app.state, "composite_principal_deployment", None)
    report = certify_demo_apis()
    assert getattr(app.state, "composite_principal_deployment", None) is previous
    with TestClient(app) as client:
        for credential in ({}, {"Authorization": "Bearer invalid"}):
            refused = client.post(
                "/performance/composites/twr",
                headers={"X-Tenant-Id": "lotus-demo", **credential},
                json={
                    "composite_id": "PB_GLOBAL_BALANCED_USD",
                    "period_start": "2026-01-01",
                    "period_end": "2026-02-28",
                },
            )
            assert refused.status_code == 401
            assert "cumulative_return" not in refused.json()

    assert report["status"] == "passed"
    assert report["api_call_count"] == 12
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
