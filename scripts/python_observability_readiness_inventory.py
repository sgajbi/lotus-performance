from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.observability_contracts import (  # noqa: E402
    PERFORMANCE_ANALYTICS_FRESHNESS_METRIC_LABELS,
    PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS,
    PERFORMANCE_MWR_SOLVER_OUTCOME_METRIC_LABELS,
)
from app.services.queue_metrics_service import DurableQueueCollector  # noqa: E402
from main import app  # noqa: E402


@dataclass(frozen=True)
class RequiredMarker:
    path: str
    marker: str
    description: str


@dataclass(frozen=True)
class ReadinessSurface:
    family: str
    expected_markers: int
    present_markers: int
    test_functions: int
    missing_markers: tuple[str, ...]


@dataclass(frozen=True)
class MonitoringArtifactValidation:
    alert_rules: int
    dashboard_panels: int
    violations: tuple[str, ...]


@dataclass(frozen=True)
class AlertDashboardCoverageRequirement:
    alert_name: str
    metric_name: str
    required_selectors: Mapping[str, str]


REQUIRED_ENDPOINTS = ("/health", "/health/live", "/health/ready", "/metrics")
DEFAULT_ALERT_RULE_PATHS = (Path("monitoring/prometheus/lotus-performance-alerts.prometheusrule.json"),)
DEFAULT_DASHBOARD_PATHS = (Path("monitoring/grafana/lotus-performance-operability-dashboard.json"),)
EXPECTED_ALERT_NAMES = frozenset(
    {
        "LotusPerformanceComputeQueueDegraded",
        "LotusPerformanceLineageQueueDegraded",
        "LotusPerformanceLineageStoragePressure",
        "LotusPerformanceRecoveryDrillPolicyBreached",
        "LotusPerformanceRuntimeRetentionPolicyBreached",
        "LotusPerformanceDurableQueueStoreUnavailable",
        "LotusPerformanceLineageStorageCapacityUnavailable",
        "LotusPerformanceRecoveryDrillHistoryUnavailable",
        "LotusPerformanceRuntimeRetentionHistoryUnavailable",
        "LotusPerformanceMWRFallbackRateElevated",
        "LotusPerformanceMWRNoRootRateElevated",
        "LotusPerformanceMWRMultipleRootRateElevated",
        "LotusPerformanceMWRSourceDataRejectionRateElevated",
        "LotusPerformanceReturnsSeriesStaleOrDegradedRateElevated",
    }
)
ALERT_DASHBOARD_COVERAGE_REQUIREMENTS = (
    AlertDashboardCoverageRequirement(
        alert_name="LotusPerformanceMWRFallbackRateElevated",
        metric_name="lotus_performance_mwr_solver_outcome_total",
        required_selectors={"fallback_used": "true"},
    ),
    AlertDashboardCoverageRequirement(
        alert_name="LotusPerformanceMWRNoRootRateElevated",
        metric_name="lotus_performance_mwr_solver_outcome_total",
        required_selectors={"reason_code": "NO_ROOT_FOUND"},
    ),
    AlertDashboardCoverageRequirement(
        alert_name="LotusPerformanceMWRMultipleRootRateElevated",
        metric_name="lotus_performance_mwr_solver_outcome_total",
        required_selectors={"reason_code": "MULTIPLE_IRR_ROOTS_DETECTED"},
    ),
    AlertDashboardCoverageRequirement(
        alert_name="LotusPerformanceMWRSourceDataRejectionRateElevated",
        metric_name="lotus_performance_calculation_supportability_total",
        required_selectors={"operation": "mwr"},
    ),
    AlertDashboardCoverageRequirement(
        alert_name="LotusPerformanceReturnsSeriesStaleOrDegradedRateElevated",
        metric_name="lotus_performance_calculation_supportability_total",
        required_selectors={"operation": "returns_series"},
    ),
)
MIN_DASHBOARD_PANELS = 10
PROMQL_METRIC_PATTERN = re.compile(r"\b(lotus_[a-zA-Z0-9_]+)\b")
PROMQL_SELECTOR_PATTERN = re.compile(r"\b(?P<metric>lotus_[a-zA-Z0-9_]+)\s*\{(?P<labels>[^}]*)\}")
PROMQL_LABEL_PATTERN = re.compile(r"\b(?P<label>[a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=~|!~|!=|=)")
PROMQL_LABEL_MATCHER_PATTERN = re.compile(
    r"\b(?P<label>[a-zA-Z_][a-zA-Z0-9_]*)\s*(?P<operator>=~|!~|!=|=)\s*\"(?P<value>[^\"]*)\""
)
SENSITIVE_LABEL_TOKENS = frozenset(
    {
        "account",
        "actor",
        "calculation",
        "client",
        "correlation",
        "customer",
        "portfolio",
        "request",
        "response",
        "security",
        "tenant",
        "trace",
        "user",
    }
)
SURFACE_MARKERS: Mapping[str, tuple[RequiredMarker, ...]] = {
    "correlation_propagation": (
        RequiredMarker("app/observability.py", "correlation_id_var", "request context correlation store"),
        RequiredMarker("app/observability.py", "resolve_correlation_id", "inbound correlation resolver"),
        RequiredMarker("app/observability.py", "propagation_headers", "outbound propagation helper"),
        RequiredMarker("app/observability.py", "X-Correlation-Id", "response propagation header"),
        RequiredMarker("app/enterprise_request_context.py", "_CORRELATION_ID_HEADER", "audit identity header"),
        RequiredMarker("app/services/core_integration_service.py", "propagation_headers", "upstream core propagation"),
    ),
    "structured_logging": (
        RequiredMarker("app/observability.py", "JsonFormatter", "JSON log formatter"),
        RequiredMarker("app/observability.py", "setup_logging", "runtime logging setup"),
        RequiredMarker("app/observability.py", "build_access_log_fields", "bounded access-log field builder"),
        RequiredMarker("app/observability.py", "request.completed", "access-log completion event"),
        RequiredMarker("app/observability.py", "duration_ms", "duration field"),
        RequiredMarker("app/observability.py", "trace_id", "trace field"),
    ),
    "metrics": (
        RequiredMarker(
            "app/observability.py", "Instrumentator().instrument(app).expose(app)", "Prometheus endpoint setup"
        ),
        RequiredMarker("app/observability.py", "Counter(", "bounded supportability counters"),
        RequiredMarker("app/observability.py", "DurableQueueCollector", "durable queue collector registration"),
        RequiredMarker(
            "app/services/queue_metrics_service.py", "class DurableQueueCollector", "queue collector implementation"
        ),
        RequiredMarker("app/services/queue_metrics_service.py", "GaugeMetricFamily", "queue gauge metric families"),
        RequiredMarker(
            "app/services/calculation_supportability_service.py",
            "record_analytics_freshness_bucket",
            "analytics freshness metric emission",
        ),
    ),
    "health_readiness": (
        RequiredMarker("app/api/endpoints/health.py", '@router.get(\n    "/health"', "health route"),
        RequiredMarker("app/api/endpoints/health.py", '@router.get(\n    "/health/live"', "liveness route"),
        RequiredMarker("app/api/endpoints/health.py", '@router.get(\n    "/health/ready"', "readiness route"),
        RequiredMarker(
            "app/api/endpoints/health.py", "check_durable_metadata_store_ready", "durable metadata readiness check"
        ),
        RequiredMarker("app/api/endpoints/health.py", "get_remediation_hint", "readiness remediation hint"),
        RequiredMarker("main.py", "application.state.is_draining", "lifespan draining state"),
    ),
}
TEST_FAMILY_TOKENS: Mapping[str, tuple[str, ...]] = {
    "correlation_propagation": ("correlation", "propagation_headers", "x-correlation-id"),
    "structured_logging": ("jsonformatter", "logging", "access_log", "request.completed"),
    "metrics": (
        "/metrics",
        "durablequeuecollector",
        "gaugemetricfamily",
        "prometheus",
        "supportability_total",
        "freshness_bucket_total",
    ),
    "health_readiness": ("/health", "health_ready", "readiness", "durable metadata", "draining"),
}


def _repository_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _present_required_marker(marker: RequiredMarker) -> bool:
    return marker.marker in _repository_text(marker.path)


def _openapi_paths(schema: Mapping[str, Any]) -> set[str]:
    paths = schema.get("paths")
    if not isinstance(paths, Mapping):
        return set()
    return {str(path) for path in paths}


def _count_test_functions_matching(tokens: Iterable[str], paths: Sequence[str]) -> int:
    normalized_tokens = tuple(token.lower() for token in tokens)
    count = 0
    for path_name in paths:
        root = (ROOT / path_name).resolve()
        candidates = [root] if root.is_file() else sorted(root.rglob("test_*.py"))
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix != ".py":
                continue
            text = candidate.read_text(encoding="utf-8")
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or not node.name.startswith("test_"):
                    continue
                source = ast.get_source_segment(text, node) or node.name
                if any(token in source.lower() for token in normalized_tokens):
                    count += 1
    return count


def collect_readiness_surfaces(
    *,
    schema: Mapping[str, Any],
    test_paths: Sequence[str],
) -> list[ReadinessSurface]:
    surfaces: list[ReadinessSurface] = []
    openapi_paths = _openapi_paths(schema)
    endpoint_missing = tuple(path for path in REQUIRED_ENDPOINTS if path not in openapi_paths)
    surfaces.append(
        ReadinessSurface(
            family="health_metrics_endpoints",
            expected_markers=len(REQUIRED_ENDPOINTS),
            present_markers=len(REQUIRED_ENDPOINTS) - len(endpoint_missing),
            test_functions=_count_test_functions_matching(("/health", "/metrics"), test_paths),
            missing_markers=endpoint_missing,
        )
    )

    for family, markers in SURFACE_MARKERS.items():
        missing = tuple(
            f"{marker.path}: {marker.description}" for marker in markers if not _present_required_marker(marker)
        )
        surfaces.append(
            ReadinessSurface(
                family=family,
                expected_markers=len(markers),
                present_markers=len(markers) - len(missing),
                test_functions=_count_test_functions_matching(TEST_FAMILY_TOKENS[family], test_paths),
                missing_markers=missing,
            )
        )
    return surfaces


def _metric_label_catalog() -> dict[str, tuple[str, ...]]:
    catalog = {
        "lotus_performance_calculation_supportability_total": PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS,
        "lotus_analytics_freshness_bucket_total": PERFORMANCE_ANALYTICS_FRESHNESS_METRIC_LABELS,
        "lotus_performance_mwr_solver_outcome_total": PERFORMANCE_MWR_SOLVER_OUTCOME_METRIC_LABELS,
    }
    for metric in DurableQueueCollector().describe():
        catalog[metric.name] = tuple(getattr(metric, "_labelnames", ()) or ())
    return catalog


def _load_json(path: Path) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _referenced_metrics(expression: str) -> set[str]:
    return set(PROMQL_METRIC_PATTERN.findall(expression))


def _referenced_selector_labels(expression: str) -> dict[str, set[str]]:
    labels_by_metric: dict[str, set[str]] = {}
    for match in PROMQL_SELECTOR_PATTERN.finditer(expression):
        labels_by_metric.setdefault(match.group("metric"), set()).update(
            PROMQL_LABEL_PATTERN.findall(match.group("labels"))
        )
    return labels_by_metric


def _referenced_selector_values(expression: str) -> dict[str, dict[str, set[str]]]:
    values_by_metric: dict[str, dict[str, set[str]]] = {}
    for match in PROMQL_SELECTOR_PATTERN.finditer(expression):
        metric_values = values_by_metric.setdefault(match.group("metric"), {})
        for label_match in PROMQL_LABEL_MATCHER_PATTERN.finditer(match.group("labels")):
            metric_values.setdefault(label_match.group("label"), set()).add(label_match.group("value"))
    return values_by_metric


def _is_sensitive_label(label: str) -> bool:
    normalized = label.lower()
    return any(token in normalized for token in SENSITIVE_LABEL_TOKENS)


def _validate_expression(
    expression: str,
    *,
    context: str,
    metric_labels: Mapping[str, tuple[str, ...]],
) -> list[str]:
    violations: list[str] = []
    for metric_name in sorted(_referenced_metrics(expression)):
        if metric_name not in metric_labels:
            violations.append(f"{context}: references unknown metric `{metric_name}`.")

    for metric_name, selector_labels in sorted(_referenced_selector_labels(expression).items()):
        known_labels = set(metric_labels.get(metric_name, ()))
        for label in sorted(selector_labels):
            if _is_sensitive_label(label):
                violations.append(f"{context}: selector label `{label}` is sensitive or high-cardinality.")
            if metric_name in metric_labels and label not in known_labels:
                violations.append(f"{context}: selector label `{label}` is not exported by `{metric_name}`.")
    return violations


def _validate_local_link(path: str, *, context: str) -> list[str]:
    if "://" in path or path.startswith("#"):
        return []
    if not path:
        return [f"{context}: link is empty."]
    target = (ROOT / path).resolve()
    try:
        target.relative_to(ROOT)
    except ValueError:
        return [f"{context}: link `{path}` leaves the repository."]
    if not target.exists():
        return [f"{context}: link `{path}` does not exist."]
    return []


def _validate_artifact_labels(labels: Mapping[str, Any], *, context: str) -> list[str]:
    violations: list[str] = []
    for label_name, label_value in labels.items():
        if _is_sensitive_label(str(label_name)):
            violations.append(f"{context}: alert label `{label_name}` is sensitive or high-cardinality.")
        if not isinstance(label_value, str) or not label_value.strip():
            violations.append(f"{context}: alert label `{label_name}` must be a non-empty string.")
    return violations


def _validate_prometheus_rule_artifact(
    path: Path,
    *,
    metric_labels: Mapping[str, tuple[str, ...]],
) -> tuple[int, list[str], set[str]]:
    violations: list[str] = []
    try:
        payload = _load_json(path)
    except Exception as exc:
        return 0, [f"{path}: cannot parse JSON alert artifact: {exc}"], set()

    if not isinstance(payload, Mapping):
        return 0, [f"{path}: alert artifact must be a JSON object."], set()
    if payload.get("kind") != "PrometheusRule":
        violations.append(f"{path}: kind must be `PrometheusRule`.")

    groups = (payload.get("spec") or {}).get("groups") if isinstance(payload.get("spec"), Mapping) else None
    if not isinstance(groups, list) or not groups:
        return 0, [*violations, f"{path}: spec.groups must be a non-empty list."], set()

    alert_names: set[str] = set()
    rule_count = 0
    for group_index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            violations.append(f"{path}: group {group_index} must be an object.")
            continue
        rules = group.get("rules")
        if not isinstance(rules, list) or not rules:
            violations.append(f"{path}: group {group_index} rules must be a non-empty list.")
            continue
        for rule_index, rule in enumerate(rules):
            context = f"{path}: group {group_index} rule {rule_index}"
            if not isinstance(rule, Mapping):
                violations.append(f"{context}: rule must be an object.")
                continue
            rule_count += 1
            alert_name = rule.get("alert")
            expression = rule.get("expr")
            duration = rule.get("for")
            labels = rule.get("labels")
            annotations = rule.get("annotations")
            if not isinstance(alert_name, str) or not alert_name.strip():
                violations.append(f"{context}: alert name is required.")
            else:
                alert_names.add(alert_name)
                context = f"{path}: alert `{alert_name}`"
            if not isinstance(expression, str) or not expression.strip():
                violations.append(f"{context}: expr is required.")
            else:
                violations.extend(_validate_expression(expression, context=context, metric_labels=metric_labels))
            if not isinstance(duration, str) or not duration.strip():
                violations.append(f"{context}: for duration is required.")
            if not isinstance(labels, Mapping):
                violations.append(f"{context}: labels must be an object.")
            else:
                for required_label in ("severity", "service", "owner"):
                    if not labels.get(required_label):
                        violations.append(f"{context}: label `{required_label}` is required.")
                if labels.get("service") != "lotus-performance":
                    violations.append(f"{context}: label `service` must be `lotus-performance`.")
                violations.extend(_validate_artifact_labels(labels, context=context))
            if not isinstance(annotations, Mapping):
                violations.append(f"{context}: annotations must be an object.")
            else:
                for required_annotation in ("summary", "description", "runbook", "dashboard"):
                    if not annotations.get(required_annotation):
                        violations.append(f"{context}: annotation `{required_annotation}` is required.")
                for link_name in ("runbook", "dashboard"):
                    link = annotations.get(link_name)
                    if isinstance(link, str):
                        violations.extend(_validate_local_link(link, context=f"{context}: annotation `{link_name}`"))

    missing_alerts = sorted(EXPECTED_ALERT_NAMES - alert_names)
    if missing_alerts:
        violations.append(f"{path}: missing expected alert(s): {', '.join(missing_alerts)}.")
    return rule_count, violations, alert_names


def _dashboard_targets(panel: Mapping[str, Any]) -> tuple[str, ...]:
    targets = panel.get("targets")
    if not isinstance(targets, list):
        return ()
    expressions: list[str] = []
    for target in targets:
        if isinstance(target, Mapping) and isinstance(target.get("expr"), str):
            expressions.append(target["expr"])
    return tuple(expressions)


def _validate_dashboard_artifact(
    path: Path,
    *,
    metric_labels: Mapping[str, tuple[str, ...]],
) -> tuple[int, list[str], tuple[str, ...]]:
    violations: list[str] = []
    dashboard_expressions: list[str] = []
    try:
        payload = _load_json(path)
    except Exception as exc:
        return 0, [f"{path}: cannot parse JSON dashboard artifact: {exc}"], ()

    if not isinstance(payload, Mapping):
        return 0, [f"{path}: dashboard artifact must be a JSON object."], ()
    if payload.get("title") != "Lotus Performance Operability":
        violations.append(f"{path}: dashboard title must be `Lotus Performance Operability`.")

    panels = payload.get("panels")
    if not isinstance(panels, list):
        return 0, [*violations, f"{path}: panels must be a list."], ()
    if len(panels) < MIN_DASHBOARD_PANELS:
        violations.append(f"{path}: dashboard must include at least {MIN_DASHBOARD_PANELS} panels.")

    for link_index, link in enumerate(payload.get("links") or []):
        if isinstance(link, Mapping) and isinstance(link.get("url"), str):
            violations.extend(_validate_local_link(link["url"], context=f"{path}: link {link_index}"))

    panel_count = 0
    for panel_index, panel in enumerate(panels):
        context = f"{path}: panel {panel_index}"
        if not isinstance(panel, Mapping):
            violations.append(f"{context}: panel must be an object.")
            continue
        panel_count += 1
        if not isinstance(panel.get("title"), str) or not panel["title"].strip():
            violations.append(f"{context}: title is required.")
        panel_expressions = _dashboard_targets(panel)
        if not panel_expressions:
            violations.append(f"{context}: at least one target expr is required.")
            continue
        dashboard_expressions.extend(panel_expressions)
        for expression_index, expression in enumerate(panel_expressions):
            violations.extend(
                _validate_expression(
                    expression,
                    context=f"{context} target {expression_index}",
                    metric_labels=metric_labels,
                )
            )
    return panel_count, violations, tuple(dashboard_expressions)


def _dashboard_expression_satisfies_requirement(
    expression: str, requirement: AlertDashboardCoverageRequirement
) -> bool:
    if requirement.metric_name not in _referenced_metrics(expression):
        return False
    selector_values = _referenced_selector_values(expression).get(requirement.metric_name, {})
    return all(
        expected in selector_values.get(label, set()) for label, expected in requirement.required_selectors.items()
    )


def _validate_alert_dashboard_coverage(
    alert_names: set[str],
    dashboard_expressions: Sequence[str],
    *,
    requirements: Sequence[AlertDashboardCoverageRequirement] = ALERT_DASHBOARD_COVERAGE_REQUIREMENTS,
) -> list[str]:
    violations: list[str] = []
    for requirement in requirements:
        if requirement.alert_name not in alert_names:
            continue
        if not any(
            _dashboard_expression_satisfies_requirement(expression, requirement) for expression in dashboard_expressions
        ):
            selectors = ", ".join(
                f'{label}="{value}"' for label, value in sorted(requirement.required_selectors.items())
            )
            violations.append(
                "monitoring dashboard coverage: alert "
                f"`{requirement.alert_name}` requires a dashboard panel referencing "
                f"`{requirement.metric_name}{{{selectors}}}`."
            )
    return violations


def collect_monitoring_artifact_validation(
    *,
    alert_rule_paths: Sequence[Path] = DEFAULT_ALERT_RULE_PATHS,
    dashboard_paths: Sequence[Path] = DEFAULT_DASHBOARD_PATHS,
    metric_labels: Mapping[str, tuple[str, ...]] | None = None,
) -> MonitoringArtifactValidation:
    resolved_metric_labels = metric_labels or _metric_label_catalog()
    alert_rules = 0
    dashboard_panels = 0
    alert_names: set[str] = set()
    dashboard_expressions: list[str] = []
    violations: list[str] = []
    for path in alert_rule_paths:
        rule_count, artifact_violations, artifact_alert_names = _validate_prometheus_rule_artifact(
            path, metric_labels=resolved_metric_labels
        )
        alert_rules += rule_count
        alert_names.update(artifact_alert_names)
        violations.extend(artifact_violations)
    for path in dashboard_paths:
        panel_count, artifact_violations, artifact_dashboard_expressions = _validate_dashboard_artifact(
            path, metric_labels=resolved_metric_labels
        )
        dashboard_panels += panel_count
        dashboard_expressions.extend(artifact_dashboard_expressions)
        violations.extend(artifact_violations)
    violations.extend(_validate_alert_dashboard_coverage(alert_names, dashboard_expressions))
    return MonitoringArtifactValidation(
        alert_rules=alert_rules,
        dashboard_panels=dashboard_panels,
        violations=tuple(violations),
    )


def render_markdown(
    surfaces: Sequence[ReadinessSurface],
    *,
    limit: int,
    monitoring_validation: MonitoringArtifactValidation | None = None,
) -> str:
    expected = sum(surface.expected_markers for surface in surfaces)
    present = sum(surface.present_markers for surface in surfaces)
    missing = expected - present
    observed_tests = sum(surface.test_functions for surface in surfaces)
    monitoring_validation = monitoring_validation or MonitoringArtifactValidation(0, 0, ())

    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Operational readiness families | {len(surfaces)} |",
        f"| Expected implementation markers | {expected} |",
        f"| Present implementation markers | {present} |",
        f"| Missing implementation markers | {missing} |",
        f"| Mapped observability/readiness test functions | {observed_tests} |",
        f"| Deployable monitoring alert rules | {monitoring_validation.alert_rules} |",
        f"| Deployable monitoring dashboard panels | {monitoring_validation.dashboard_panels} |",
        f"| Monitoring artifact violations | {len(monitoring_validation.violations)} |",
        "",
        "Mapped test functions are counted per readiness family and can overlap when one test proves multiple operational contracts.",
        "",
        "## Surface Coverage",
        "",
        "| Family | Present markers | Expected markers | Test functions | Missing markers |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for surface in surfaces:
        lines.append(
            f"| `{surface.family}` | {surface.present_markers} | {surface.expected_markers} | "
            f"{surface.test_functions} | {len(surface.missing_markers)} |"
        )

    lines.extend(["", "## Missing Markers", "", "| Family | Marker |", "| --- | --- |"])
    rendered = 0
    for surface in surfaces:
        for missing_marker in surface.missing_markers[: max(limit - rendered, 0)]:
            lines.append(f"| `{surface.family}` | `{missing_marker}` |")
            rendered += 1
            if rendered >= limit:
                break
        if rendered >= limit:
            break
    if rendered == 0:
        lines.append("| none | none |")
    lines.extend(["", "## Monitoring Artifact Violations", "", "| Finding |", "| --- |"])
    if monitoring_validation.violations:
        for violation in monitoring_validation.violations[:limit]:
            lines.append(f"| `{violation}` |")
    else:
        lines.append("| none |")
    return "\n".join(lines)


def observability_threshold_violations(
    surfaces: Sequence[ReadinessSurface],
    *,
    max_missing: int | None,
) -> list[str]:
    if max_missing is None:
        return []

    missing = sum(surface.expected_markers - surface.present_markers for surface in surfaces)
    if missing <= max_missing:
        return []

    return [
        f"Observability readiness gate failed: {missing} missing marker(s) exceed configured maximum {max_missing}."
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Lotus performance observability/readiness surfaces")
    parser.add_argument("--test-path", action="append", dest="test_paths", help="Test path to scan")
    parser.add_argument("--limit", type=int, default=30, help="Maximum missing-marker rows to render")
    parser.add_argument(
        "--max-missing",
        type=int,
        default=None,
        help="Fail when missing implementation markers exceed this maximum",
    )
    args = parser.parse_args()

    test_paths = tuple(args.test_paths or ("tests",))
    surfaces = collect_readiness_surfaces(schema=app.openapi(), test_paths=test_paths)
    monitoring_validation = collect_monitoring_artifact_validation()
    print(render_markdown(surfaces, limit=args.limit, monitoring_validation=monitoring_validation))
    violations = observability_threshold_violations(surfaces, max_missing=args.max_missing)
    violations.extend(monitoring_validation.violations)
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
