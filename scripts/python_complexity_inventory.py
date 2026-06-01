from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ("app", "engine", "core", "adapters")


@dataclass(frozen=True)
class ComplexityFinding:
    path: str
    name: str
    kind: str
    rank: str
    complexity: int
    line: int
    end_line: int


@dataclass(frozen=True)
class MaintainabilityFinding:
    path: str
    rank: str
    maintainability_index: float


def _run_radon(args: Sequence[str]) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "radon", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def parse_complexity_payload(payload: Mapping[str, Any]) -> list[ComplexityFinding]:
    findings: list[ComplexityFinding] = []
    for raw_path, entries in payload.items():
        path = _normalize_path(raw_path)
        for entry in entries:
            findings.append(
                ComplexityFinding(
                    path=path,
                    name=str(entry["name"]),
                    kind=str(entry["type"]),
                    rank=str(entry["rank"]),
                    complexity=int(entry["complexity"]),
                    line=int(entry["lineno"]),
                    end_line=int(entry.get("endline") or entry["lineno"]),
                )
            )
    return sorted(findings, key=lambda item: (-item.complexity, item.path, item.line, item.name))


def parse_maintainability_payload(payload: Mapping[str, Any]) -> list[MaintainabilityFinding]:
    findings: list[MaintainabilityFinding] = []
    for raw_path, entry in payload.items():
        findings.append(
            MaintainabilityFinding(
                path=_normalize_path(raw_path),
                rank=str(entry["rank"]),
                maintainability_index=float(entry["mi"]),
            )
        )
    return sorted(findings, key=lambda item: (item.maintainability_index, item.path))


def collect_complexity(paths: Sequence[str] = DEFAULT_PATHS) -> list[ComplexityFinding]:
    output = _run_radon(["cc", "--json", "--show-complexity", *paths])
    return parse_complexity_payload(json.loads(output))


def collect_maintainability(paths: Sequence[str] = DEFAULT_PATHS) -> list[MaintainabilityFinding]:
    output = _run_radon(["mi", "--json", *paths])
    return parse_maintainability_payload(json.loads(output))


def _rank_count(findings: Sequence[ComplexityFinding], ranks: set[str]) -> int:
    return sum(1 for finding in findings if finding.rank in ranks)


def render_markdown(
    complexity_findings: Sequence[ComplexityFinding],
    maintainability_findings: Sequence[MaintainabilityFinding],
    *,
    limit: int,
) -> str:
    top_complexity = list(complexity_findings[:limit])
    lowest_maintainability = list(maintainability_findings[:limit])
    average_mi = (
        mean(finding.maintainability_index for finding in maintainability_findings) if maintainability_findings else 0.0
    )
    high_complexity_ranks = {"D", "E", "F"}

    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Max cyclomatic complexity | {top_complexity[0].complexity if top_complexity else 0} |",
        f"| High-complexity functions (rank D-F) | {_rank_count(complexity_findings, high_complexity_ranks)} |",
        f"| Average maintainability index | {average_mi:.2f} |",
        "",
        "## Highest Cyclomatic Complexity",
        "",
        "| Rank | Symbol | Type | File | CC | Grade |",
        "| ---: | --- | --- | --- | ---: | --- |",
    ]
    for index, complexity_finding in enumerate(top_complexity, start=1):
        lines.append(
            f"| {index} | `{complexity_finding.name}` | {complexity_finding.kind} | "
            f"`{complexity_finding.path}:{complexity_finding.line}` | "
            f"{complexity_finding.complexity} | {complexity_finding.rank} |"
        )

    lines.extend(
        [
            "",
            "## Lowest Maintainability Index",
            "",
            "| Rank | File | MI | Grade |",
            "| ---: | --- | ---: | --- |",
        ]
    )
    for index, maintainability_finding in enumerate(lowest_maintainability, start=1):
        lines.append(
            f"| {index} | `{maintainability_finding.path}` | "
            f"{maintainability_finding.maintainability_index:.2f} | {maintainability_finding.rank} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Python cyclomatic complexity and maintainability")
    parser.add_argument("--path", action="append", dest="paths", help="Path to scan relative to the repository root")
    parser.add_argument("--limit", type=int, default=15, help="Maximum rows per inventory table")
    args = parser.parse_args()

    paths = tuple(args.paths or DEFAULT_PATHS)
    print(render_markdown(collect_complexity(paths), collect_maintainability(paths), limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
