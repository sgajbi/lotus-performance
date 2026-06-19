from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ("app", "engine", "core", "adapters")


@dataclass(frozen=True)
class BanditIssue:
    severity: str
    confidence: str
    test_id: str
    test_name: str
    filename: str
    line_number: int
    issue_text: str


@dataclass(frozen=True)
class BanditScan:
    issues: list[BanditIssue]
    lines_scanned: int
    nosec_count: int
    skipped_tests: int


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def build_bandit_command(paths: Sequence[str] = DEFAULT_PATHS) -> list[str]:
    return [sys.executable, "-m", "bandit", "-q", "-r", *paths, "-f", "json"]


def parse_bandit_payload(payload: Mapping[str, Any]) -> list[BanditIssue]:
    issues: list[BanditIssue] = []
    for item in payload.get("results", []):
        issues.append(
            BanditIssue(
                severity=str(item["issue_severity"]),
                confidence=str(item["issue_confidence"]),
                test_id=str(item["test_id"]),
                test_name=str(item["test_name"]),
                filename=_normalize_path(str(item["filename"])),
                line_number=int(item["line_number"]),
                issue_text=str(item["issue_text"]),
            )
        )
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNDEFINED": 3}
    return sorted(
        issues,
        key=lambda issue: (
            severity_order.get(issue.severity, 99),
            issue.test_id,
            issue.filename,
            issue.line_number,
            issue.issue_text,
        ),
    )


def _int_metric(metrics: Mapping[str, Any], name: str) -> int:
    value = metrics.get(name, 0)
    return value if isinstance(value, int) else 0


def parse_bandit_scan(payload: Mapping[str, Any]) -> BanditScan:
    totals = payload.get("metrics", {}).get("_totals", {})
    metrics = totals if isinstance(totals, Mapping) else {}
    return BanditScan(
        issues=parse_bandit_payload(payload),
        lines_scanned=_int_metric(metrics, "loc"),
        nosec_count=_int_metric(metrics, "nosec"),
        skipped_tests=_int_metric(metrics, "skipped_tests"),
    )


def _load_bandit_payload(stdout: str) -> Mapping[str, Any]:
    if not stdout.strip():
        raise RuntimeError("Bandit did not produce a JSON report.")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Bandit did not produce a valid JSON report.") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("Bandit JSON report had an unexpected shape.")
    if not isinstance(payload.get("metrics"), Mapping) or not isinstance(payload.get("results"), list):
        raise RuntimeError("Bandit JSON report is missing required metrics or results.")
    return payload


def collect_bandit_scan(paths: Sequence[str] = DEFAULT_PATHS) -> BanditScan:
    completed = subprocess.run(
        build_bandit_command(paths),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    payload = _load_bandit_payload(completed.stdout)
    return parse_bandit_scan(payload)


def collect_bandit_issues(paths: Sequence[str] = DEFAULT_PATHS) -> list[BanditIssue]:
    return collect_bandit_scan(paths).issues


def _count_by_path_prefix(issues: Sequence[BanditIssue], prefixes: Mapping[str, str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for issue in issues:
        label = "Other"
        for prefix, prefix_label in prefixes.items():
            if issue.filename.startswith(prefix):
                label = prefix_label
                break
        counts[label] += 1
    return counts


def _count(issues: Sequence[BanditIssue], field: str) -> Counter[str]:
    return Counter(str(getattr(issue, field)) for issue in issues)


def render_markdown(
    issues: Sequence[BanditIssue],
    *,
    limit: int,
    lines_scanned: int = 0,
    nosec_count: int = 0,
    skipped_tests: int = 0,
) -> str:
    severity_counts = _count(issues, "severity")
    confidence_counts = _count(issues, "confidence")
    test_counts = _count(issues, "test_id")
    area_counts = _count_by_path_prefix(
        issues,
        {
            "app/api/endpoints/": "API endpoints",
            "app/models/": "Application models",
            "app/services/": "Services",
            "app/": "Application",
            "engine/": "Engine",
            "core/": "Core",
            "adapters/": "Adapters",
        },
    )

    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total Bandit findings | {len(issues)} |",
        f"| High severity findings | {severity_counts['HIGH']} |",
        f"| Medium severity findings | {severity_counts['MEDIUM']} |",
        f"| Low severity findings | {severity_counts['LOW']} |",
        f"| Distinct test IDs | {len(test_counts)} |",
        f"| Lines scanned | {lines_scanned} |",
        f"| `nosec` markers | {nosec_count} |",
        f"| Targeted skipped tests | {skipped_tests} |",
        "",
        "## Findings By Severity",
        "",
        "| Severity | Count |",
        "| --- | ---: |",
    ]
    for severity in ("HIGH", "MEDIUM", "LOW", "UNDEFINED"):
        if severity_counts[severity]:
            lines.append(f"| {severity} | {severity_counts[severity]} |")

    lines.extend(["", "## Findings By Confidence", "", "| Confidence | Count |", "| --- | ---: |"])
    for confidence, count in sorted(confidence_counts.items()):
        lines.append(f"| {confidence} | {count} |")

    lines.extend(["", "## Findings By Test", "", "| Test ID | Count |", "| --- | ---: |"])
    for test_id, count in sorted(test_counts.items()):
        lines.append(f"| {test_id} | {count} |")

    lines.extend(["", "## Findings By Area", "", "| Area | Count |", "| --- | ---: |"])
    for area, count in sorted(area_counts.items()):
        lines.append(f"| {area} | {count} |")

    lines.extend(
        [
            "",
            "## Findings",
            "",
            "| Rank | Severity | Confidence | Test | Location | Issue |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for index, issue in enumerate(issues[:limit], start=1):
        location = f"{issue.filename}:{issue.line_number}"
        test = f"{issue.test_id} {issue.test_name}"
        lines.append(
            "| "
            f"{index} | {issue.severity} | {issue.confidence} | `{test}` | `{location}` | "
            f"{_escape_markdown_cell(issue.issue_text)} |"
        )
    return "\n".join(lines)


def security_threshold_violations(
    issues: Sequence[BanditIssue],
    *,
    max_high: int | None = None,
    max_medium: int | None = None,
    max_low: int | None = None,
) -> list[str]:
    severity_counts = _count(issues, "severity")
    thresholds = (
        ("HIGH", max_high),
        ("MEDIUM", max_medium),
        ("LOW", max_low),
    )
    violations: list[str] = []
    for severity, maximum in thresholds:
        if maximum is None or severity_counts[severity] <= maximum:
            continue
        violations.append(
            "Python security gate failed: "
            f"{severity.lower()} severity findings {severity_counts[severity]} exceed configured maximum {maximum}."
        )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Python security findings with Bandit")
    parser.add_argument("--path", action="append", dest="paths", help="Path to scan relative to the repository root")
    parser.add_argument("--limit", type=int, default=30, help="Maximum rows in the findings table")
    parser.add_argument("--max-high", type=int, help="Fail when high severity findings exceed this value")
    parser.add_argument("--max-medium", type=int, help="Fail when medium severity findings exceed this value")
    parser.add_argument("--max-low", type=int, help="Fail when low severity findings exceed this value")
    args = parser.parse_args()

    paths = tuple(args.paths or DEFAULT_PATHS)
    scan = collect_bandit_scan(paths)
    print(
        render_markdown(
            scan.issues,
            limit=args.limit,
            lines_scanned=scan.lines_scanned,
            nosec_count=scan.nosec_count,
            skipped_tests=scan.skipped_tests,
        )
    )
    violations = security_threshold_violations(
        scan.issues,
        max_high=args.max_high,
        max_medium=args.max_medium,
        max_low=args.max_low,
    )
    for violation in violations:
        print(violation)
    if violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
