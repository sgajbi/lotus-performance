from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE_JSON = ROOT / "output" / "branch-coverage" / "coverage.json"
DEFAULT_OUTPUT = ROOT / "quality" / "coverage_inventory.md"


@dataclass(frozen=True)
class FileBranchCoverage:
    path: str
    covered_branches: int
    missing_branches: int
    partial_branches: int
    total_branches: int


@dataclass(frozen=True)
class BranchCoverageSnapshot:
    report_date: str
    branch: str
    coverage_version: str
    branch_coverage_enabled: bool
    covered_lines: int
    missing_lines: int
    total_statements: int
    line_coverage_percent: Decimal
    covered_branches: int
    missing_branches: int
    partial_branches: int
    total_branches: int
    top_branch_gaps: tuple[FileBranchCoverage, ...]

    @property
    def branch_coverage_percent(self) -> Decimal | None:
        if not self.total_branches:
            return None
        return (Decimal(self.covered_branches) / Decimal(self.total_branches)) * Decimal("100")


def _int(value: Any) -> int:
    return int(value or 0)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _git_value(args: tuple[str, ...], *, root: Path = ROOT) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _format_percent(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    return f"{value.quantize(Decimal('0.01'))}%"


def load_branch_coverage_snapshot(
    coverage_json_path: Path,
    *,
    report_date: str | None = None,
    root: Path = ROOT,
) -> BranchCoverageSnapshot:
    coverage = json.loads(coverage_json_path.read_text(encoding="utf-8"))
    totals = coverage.get("totals", {})
    meta = coverage.get("meta", {})

    branch_gap_rows: list[FileBranchCoverage] = []
    for path, file_coverage in sorted(coverage.get("files", {}).items()):
        summary = file_coverage.get("summary", {})
        missing_branches = _int(summary.get("missing_branches"))
        partial_branches = _int(summary.get("num_partial_branches"))
        total_branches = _int(summary.get("num_branches"))
        if missing_branches or partial_branches:
            branch_gap_rows.append(
                FileBranchCoverage(
                    path=path.replace("\\", "/"),
                    covered_branches=_int(summary.get("covered_branches")),
                    missing_branches=missing_branches,
                    partial_branches=partial_branches,
                    total_branches=total_branches,
                )
            )

    branch_gap_rows.sort(key=lambda row: (-row.missing_branches, -row.partial_branches, -row.total_branches, row.path))

    return BranchCoverageSnapshot(
        report_date=report_date or datetime.now().date().isoformat(),
        branch=_git_value(("branch", "--show-current"), root=root),
        coverage_version=str(meta.get("version") or "unknown"),
        branch_coverage_enabled=bool(meta.get("branch_coverage")),
        covered_lines=_int(totals.get("covered_lines")),
        missing_lines=_int(totals.get("missing_lines")),
        total_statements=_int(totals.get("num_statements")),
        line_coverage_percent=_decimal(totals.get("percent_covered")),
        covered_branches=_int(totals.get("covered_branches")),
        missing_branches=_int(totals.get("missing_branches")),
        partial_branches=_int(totals.get("num_partial_branches")),
        total_branches=_int(totals.get("num_branches")),
        top_branch_gaps=tuple(branch_gap_rows[:10]),
    )


def render_branch_coverage_inventory(snapshot: BranchCoverageSnapshot) -> str:
    top_gap_rows = "\n".join(
        f"| `{row.path}` | {row.covered_branches} | {row.missing_branches} | "
        f"{row.partial_branches} | {row.total_branches} |"
        for row in snapshot.top_branch_gaps
    )
    if not top_gap_rows:
        top_gap_rows = "| _No missing or partial branch rows reported._ | 0 | 0 | 0 | 0 |"

    branch_status = "enabled" if snapshot.branch_coverage_enabled else "not enabled"
    branch_percent = _format_percent(snapshot.branch_coverage_percent)

    return f"""# Lotus Performance Coverage Inventory

Report date: {snapshot.report_date}
Branch: `{snapshot.branch}`
Mode: report-only local coverage evidence; the blocking line-coverage gate remains unchanged.

## Purpose

This report captures the current repository-native coverage posture for the performance hardening
stream. Line coverage remains enforced separately through `make test-coverage` and the PR/main
coverage gates. Branch coverage is now measured as report-only evidence so the repository can
establish a baseline, review false positives, and decide future lane placement without creating a
noisy blocker.

## Command

```powershell
make branch-coverage-baseline
```

## Coverage Gate Posture

| Metric | Value | Evidence |
| --- | ---: | --- |
| Branch coverage collection | {branch_status} | `pytest --cov-branch` in `make branch-coverage-baseline` |
| Combined line coverage under branch run | {_format_percent(snapshot.line_coverage_percent)} | `coverage json` totals from `output/branch-coverage/coverage.json` |
| Covered lines | {snapshot.covered_lines} | coverage.py `{snapshot.coverage_version}` JSON totals |
| Missing lines | {snapshot.missing_lines} | coverage.py `{snapshot.coverage_version}` JSON totals |
| Statements | {snapshot.total_statements} | coverage.py `{snapshot.coverage_version}` JSON totals |
| Combined branch coverage | {branch_percent} | {snapshot.covered_branches} covered branches of {snapshot.total_branches} total branches |
| Missing branches | {snapshot.missing_branches} | coverage.py `{snapshot.coverage_version}` JSON totals |
| Partial branches | {snapshot.partial_branches} | coverage.py `{snapshot.coverage_version}` JSON totals |
| Branch-coverage gate | not configured | Report-only baseline; no fail-under threshold is applied. |
| Existing line-coverage gate | unchanged | `make test-coverage` still enforces `coverage report --fail-under=99`. |

## Top Branch Coverage Gaps

| File | Covered branches | Missing branches | Partial branches | Total branches |
| --- | ---: | ---: | ---: | ---: |
{top_gap_rows}

## CI Alignment

The PR Merge Gate and Main Releasability workflows continue to enforce the combined 99% line
coverage floor. This report does not introduce a new blocking gate. It creates the accepted
measurement surface needed before any branch-coverage threshold, diff-coverage policy, exception
policy, or GitHub lane placement can be proposed.

## Follow-Up

Branch coverage should remain report-only until the repo has:

1. repeated baseline runs across local and GitHub evidence,
2. reviewed exclusions for framework, generated-model, and defensive branch gaps,
3. an exception policy for low-value glue-code branches,
4. remediation guidance for branch gaps that hide business or operator behavior,
5. CI lane placement that does not duplicate the existing 99% line-coverage gate.
"""


def write_or_check_report(snapshot: BranchCoverageSnapshot, *, output_path: Path, write: bool) -> int:
    rendered = render_branch_coverage_inventory(snapshot)
    if write:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        return 0

    existing = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    if existing == rendered:
        return 0
    try:
        display_path = output_path.relative_to(ROOT)
    except ValueError:
        display_path = output_path
    print(f"{display_path} is stale. Run `make branch-coverage-baseline`.", file=sys.stderr)
    return 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the report-only branch coverage inventory.")
    parser.add_argument("--coverage-json", type=Path, default=DEFAULT_COVERAGE_JSON)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-date")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.write and args.check:
        print("Use only one of --write or --check.", file=sys.stderr)
        return 2
    if not args.coverage_json.exists():
        print(f"Coverage JSON not found: {args.coverage_json}", file=sys.stderr)
        return 1

    snapshot = load_branch_coverage_snapshot(args.coverage_json, report_date=args.report_date)
    if args.write:
        return write_or_check_report(snapshot, output_path=args.output, write=True)
    if args.check:
        return write_or_check_report(snapshot, output_path=args.output, write=False)

    print(render_branch_coverage_inventory(snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
