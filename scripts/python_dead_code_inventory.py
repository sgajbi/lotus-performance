from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ("app", "engine", "core", "adapters")
DEFAULT_MIN_CONFIDENCE = 60
_FINDING_PATTERN = re.compile(
    r"^(?P<path>.+):(?P<line>\d+): unused (?P<kind>\w+) " r"'(?P<name>[^']+)' \((?P<confidence>\d+)% confidence\)$"
)


@dataclass(frozen=True)
class DeadCodeFinding:
    path: str
    line: int
    kind: str
    name: str
    confidence: int


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def parse_vulture_output(output: str) -> list[DeadCodeFinding]:
    findings: list[DeadCodeFinding] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _FINDING_PATTERN.match(line)
        if match is None:
            continue
        findings.append(
            DeadCodeFinding(
                path=_normalize_path(match.group("path")),
                line=int(match.group("line")),
                kind=match.group("kind"),
                name=match.group("name"),
                confidence=int(match.group("confidence")),
            )
        )
    return sorted(findings, key=lambda item: (-item.confidence, item.path, item.line, item.kind, item.name))


def collect_dead_code(
    paths: Sequence[str] = DEFAULT_PATHS,
    *,
    min_confidence: int = DEFAULT_MIN_CONFIDENCE,
) -> list[DeadCodeFinding]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "vulture",
            *paths,
            "--min-confidence",
            str(min_confidence),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in {0, 3}:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return parse_vulture_output("\n".join([completed.stdout, completed.stderr]))


def _count_by_path_prefix(findings: Sequence[DeadCodeFinding], prefixes: Mapping[str, str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for finding in findings:
        label = "Other"
        for prefix, prefix_label in prefixes.items():
            if finding.path.startswith(prefix):
                label = prefix_label
                break
        counts[label] += 1
    return counts


def render_markdown(findings: Sequence[DeadCodeFinding], *, limit: int, min_confidence: int) -> str:
    kind_counts = Counter(finding.kind for finding in findings)
    area_counts = _count_by_path_prefix(
        findings,
        {
            "app/api/endpoints/": "API endpoints",
            "app/models/": "Pydantic models",
            "app/services/": "Services",
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
        f"| Minimum confidence | {min_confidence}% |",
        f"| Total findings | {len(findings)} |",
        f"| Distinct files with findings | {len({finding.path for finding in findings})} |",
        "",
        "## Findings By Kind",
        "",
        "| Kind | Count |",
        "| --- | ---: |",
    ]
    for kind, count in sorted(kind_counts.items()):
        lines.append(f"| {kind} | {count} |")

    lines.extend(["", "## Findings By Area", "", "| Area | Count |", "| --- | ---: |"])
    for area, count in sorted(area_counts.items()):
        lines.append(f"| {area} | {count} |")

    lines.extend(
        [
            "",
            "## Top Findings",
            "",
            "| Rank | File | Symbol | Kind | Confidence |",
            "| ---: | --- | --- | --- | ---: |",
        ]
    )
    for index, finding in enumerate(findings[:limit], start=1):
        lines.append(
            f"| {index} | `{finding.path}:{finding.line}` | `{finding.name}` | {finding.kind} | {finding.confidence}% |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory vulture dead-code findings for production Python paths")
    parser.add_argument("--path", action="append", dest="paths", help="Path to scan relative to the repository root")
    parser.add_argument("--limit", type=int, default=30, help="Maximum rows in the top-findings table")
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=DEFAULT_MIN_CONFIDENCE,
        help="Minimum vulture confidence to report",
    )
    args = parser.parse_args()

    paths = tuple(args.paths or DEFAULT_PATHS)
    findings = collect_dead_code(paths, min_confidence=args.min_confidence)
    print(render_markdown(findings, limit=args.limit, min_confidence=args.min_confidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
