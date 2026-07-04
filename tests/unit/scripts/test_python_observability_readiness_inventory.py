import json
from pathlib import Path

from scripts.python_observability_readiness_inventory import (
    EXPECTED_ALERT_NAMES,
    collect_monitoring_artifact_validation,
    collect_readiness_surfaces,
    observability_threshold_violations,
    render_markdown,
)


def test_collect_readiness_surfaces_reports_endpoint_and_marker_coverage() -> None:
    surfaces = collect_readiness_surfaces(
        schema={"paths": {"/health": {}, "/health/live": {}, "/health/ready": {}, "/metrics": {}}},
        test_paths=("tests/unit/test_observability.py",),
    )

    by_family = {surface.family: surface for surface in surfaces}

    assert by_family["health_metrics_endpoints"].present_markers == 4
    assert by_family["health_metrics_endpoints"].expected_markers == 4
    assert by_family["correlation_propagation"].present_markers == 6
    assert by_family["structured_logging"].present_markers == 6
    assert by_family["metrics"].present_markers == 6
    assert by_family["health_readiness"].present_markers == 6
    assert by_family["correlation_propagation"].test_functions > 0


def test_render_markdown_summarizes_missing_markers() -> None:
    surfaces = collect_readiness_surfaces(
        schema={"paths": {"/health": {}, "/metrics": {}}},
        test_paths=("tests/unit/test_observability.py",),
    )

    output = render_markdown(surfaces, limit=5)

    assert "| Operational readiness families | 5 |" in output
    assert "| Expected implementation markers | 28 |" in output
    assert "| Missing implementation markers | 2 |" in output
    assert "`/health/live`" in output
    assert "`/health/ready`" in output
    assert "| Deployable monitoring alert rules | 0 |" in output


def test_observability_threshold_violations_allows_clean_inventory() -> None:
    surfaces = collect_readiness_surfaces(
        schema={"paths": {"/health": {}, "/health/live": {}, "/health/ready": {}, "/metrics": {}}},
        test_paths=("tests/unit/test_observability.py",),
    )

    assert observability_threshold_violations(surfaces, max_missing=0) == []


def test_observability_threshold_violations_enforces_missing_marker_gate() -> None:
    surfaces = collect_readiness_surfaces(
        schema={"paths": {"/health": {}, "/metrics": {}}},
        test_paths=("tests/unit/test_observability.py",),
    )

    assert observability_threshold_violations(surfaces, max_missing=1) == [
        "Observability readiness gate failed: 2 missing marker(s) exceed configured maximum 1."
    ]


def test_monitoring_artifact_validation_accepts_current_deployable_artifacts() -> None:
    validation = collect_monitoring_artifact_validation()

    assert validation.alert_rules == len(EXPECTED_ALERT_NAMES)
    assert validation.dashboard_panels >= 10
    assert validation.violations == ()


def test_monitoring_artifact_validation_rejects_unknown_metrics_and_sensitive_alert_labels(tmp_path: Path) -> None:
    alert_path = tmp_path / "invalid.prometheusrule.json"
    alert_path.write_text(
        json.dumps(
            {
                "kind": "PrometheusRule",
                "spec": {
                    "groups": [
                        {
                            "name": "invalid",
                            "rules": [
                                {
                                    "alert": "LotusPerformanceUnsafeAlert",
                                    "expr": "lotus_performance_missing_metric_total > 0",
                                    "for": "5m",
                                    "labels": {
                                        "severity": "page",
                                        "service": "lotus-performance",
                                        "owner": "performance-platform-operations",
                                        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                                    },
                                    "annotations": {
                                        "summary": "unsafe",
                                        "description": "unsafe",
                                        "runbook": "docs/runbooks/runtime-alerts.md",
                                        "dashboard": "monitoring/grafana/lotus-performance-operability-dashboard.json",
                                    },
                                }
                            ],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    validation = collect_monitoring_artifact_validation(alert_rule_paths=(alert_path,), dashboard_paths=())

    assert any(
        "references unknown metric `lotus_performance_missing_metric_total`" in violation
        for violation in validation.violations
    )
    assert any("alert label `portfolio_id` is sensitive" in violation for violation in validation.violations)


def test_monitoring_artifact_validation_rejects_unknown_and_sensitive_selector_labels(tmp_path: Path) -> None:
    dashboard_path = tmp_path / "invalid-dashboard.json"
    dashboard_path.write_text(
        json.dumps(
            {
                "title": "Lotus Performance Operability",
                "links": [{"url": "docs/runbooks/runtime-alerts.md"}],
                "panels": [
                    {
                        "title": "Unsafe selector",
                        "targets": [
                            {"expr": 'lotus_performance_mwr_solver_outcome_total{portfolio_id="PB_SG_GLOBAL_BAL_001"}'}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    validation = collect_monitoring_artifact_validation(alert_rule_paths=(), dashboard_paths=(dashboard_path,))

    assert any("selector label `portfolio_id` is sensitive" in violation for violation in validation.violations)
    assert any(
        "selector label `portfolio_id` is not exported by `lotus_performance_mwr_solver_outcome_total`" in violation
        for violation in validation.violations
    )
