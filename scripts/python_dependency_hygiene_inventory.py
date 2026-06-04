from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = (".",)
DEFAULT_FIRST_PARTY = ("app", "engine", "core", "adapters", "common", "scripts")
DEFAULT_PER_RULE_IGNORES = {
    "DEP002": ("psycopg", "uvicorn"),
}


@dataclass(frozen=True)
class DependencyIssue:
    code: str
    module: str
    message: str
    path: str
    line: int | None
    column: int | None


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def parse_deptry_payload(payload: Sequence[Mapping[str, Any]]) -> list[DependencyIssue]:
    issues: list[DependencyIssue] = []
    for item in payload:
        error = item["error"]
        location = item["location"]
        issues.append(
            DependencyIssue(
                code=str(error["code"]),
                module=str(item["module"]),
                message=str(error["message"]),
                path=_normalize_path(str(location["file"])),
                line=int(location["line"]) if location["line"] is not None else None,
                column=int(location["column"]) if location["column"] is not None else None,
            )
        )
    return sorted(issues, key=lambda item: (item.code, item.module, item.path, item.line or 0, item.column or 0))


def _format_per_rule_ignores(per_rule_ignores: Mapping[str, Sequence[str]]) -> str:
    return ",".join(
        f"{rule}={'|'.join(sorted(modules))}" for rule, modules in sorted(per_rule_ignores.items()) if modules
    )


def build_deptry_command(
    paths: Sequence[str],
    *,
    output_path: Path,
    known_first_party: Sequence[str] = DEFAULT_FIRST_PARTY,
    per_rule_ignores: Mapping[str, Sequence[str]] = DEFAULT_PER_RULE_IGNORES,
) -> list[str]:
    command = [sys.executable, "-m", "deptry", *paths, "--json-output", str(output_path), "--no-ansi"]
    for module_name in known_first_party:
        command.extend(["--known-first-party", module_name])
    formatted_per_rule_ignores = _format_per_rule_ignores(per_rule_ignores)
    if formatted_per_rule_ignores:
        command.extend(["--per-rule-ignores", formatted_per_rule_ignores])
    return command


def collect_dependency_issues(
    paths: Sequence[str] = DEFAULT_PATHS,
    *,
    known_first_party: Sequence[str] = DEFAULT_FIRST_PARTY,
    per_rule_ignores: Mapping[str, Sequence[str]] = DEFAULT_PER_RULE_IGNORES,
) -> list[DependencyIssue]:
    with tempfile.TemporaryDirectory(prefix="lotus-deptry-") as temp_dir_name:
        output_path = Path(temp_dir_name) / "deptry-report.json"
        command = build_deptry_command(
            paths,
            output_path=output_path,
            known_first_party=known_first_party,
            per_rule_ignores=per_rule_ignores,
        )
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode not in {0, 1}:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
        payload = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else []
    return parse_deptry_payload(payload)


def _count_by_path_prefix(issues: Sequence[DependencyIssue], prefixes: Mapping[str, str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for issue in issues:
        label = "Other"
        for prefix, prefix_label in prefixes.items():
            if issue.path.startswith(prefix):
                label = prefix_label
                break
        counts[label] += 1
    return counts


def render_markdown(issues: Sequence[DependencyIssue], *, limit: int) -> str:
    code_counts = Counter(issue.code for issue in issues)
    module_counts = Counter(issue.module for issue in issues)
    area_counts = _count_by_path_prefix(
        issues,
        {
            "app/api/endpoints/": "API endpoints",
            "app/services/": "Services",
            "app/": "Application",
            "engine/": "Engine",
            "core/": "Core",
            "adapters/": "Adapters",
            "pyproject.toml": "Dependency declarations",
        },
    )

    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total dependency hygiene findings | {len(issues)} |",
        f"| Distinct issue codes | {len(code_counts)} |",
        f"| Distinct modules | {len(module_counts)} |",
        "",
        "## Findings By Code",
        "",
        "| Code | Count |",
        "| --- | ---: |",
    ]
    for code, count in sorted(code_counts.items()):
        lines.append(f"| {code} | {count} |")

    lines.extend(["", "## Findings By Module", "", "| Module | Count |", "| --- | ---: |"])
    for module, count in sorted(module_counts.items()):
        lines.append(f"| `{module}` | {count} |")

    lines.extend(["", "## Findings By Area", "", "| Area | Count |", "| --- | ---: |"])
    for area, count in sorted(area_counts.items()):
        lines.append(f"| {area} | {count} |")

    lines.extend(
        [
            "",
            "## Findings",
            "",
            "| Rank | Code | Module | Location | Message |",
            "| ---: | --- | --- | --- | --- |",
        ]
    )
    for index, issue in enumerate(issues[:limit], start=1):
        location = issue.path if issue.line is None else f"{issue.path}:{issue.line}"
        lines.append(f"| {index} | {issue.code} | `{issue.module}` | `{location}` | {issue.message} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Python dependency hygiene findings with deptry")
    parser.add_argument("--path", action="append", dest="paths", help="Path to scan relative to the repository root")
    parser.add_argument("--limit", type=int, default=30, help="Maximum rows in the findings table")
    args = parser.parse_args()

    paths = tuple(args.paths or DEFAULT_PATHS)
    print(render_markdown(collect_dependency_issues(paths), limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
