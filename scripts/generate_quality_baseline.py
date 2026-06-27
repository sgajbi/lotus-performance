from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUALITY_DIR = ROOT / "quality"
DEFAULT_INVENTORY_OUTPUT_DIR = ROOT / "output" / "quality-baseline"


@dataclass(frozen=True)
class InventoryCommand:
    output_path: Path
    argv: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryStatistics:
    report_date: str
    branch: str
    commit: str
    python_files: int
    package_markers: int
    python_loc: int
    test_modules: int
    collected_tests: str
    configured_workflows: int
    largest_python_files: tuple[tuple[str, int], ...]


INVENTORY_COMMANDS: tuple[InventoryCommand, ...] = (
    InventoryCommand(
        QUALITY_DIR / "function_size_inventory.md",
        ("scripts/python_function_size_inventory.py", "--limit", "15"),
    ),
    InventoryCommand(
        QUALITY_DIR / "complexity_inventory.md",
        ("scripts/python_complexity_inventory.py", "--limit", "15"),
    ),
    InventoryCommand(
        QUALITY_DIR / "dead_code_inventory.md",
        ("scripts/python_dead_code_inventory.py", "--limit", "30", "--min-confidence", "60"),
    ),
    InventoryCommand(
        QUALITY_DIR / "dependency_hygiene_report.md",
        ("scripts/python_dependency_hygiene_inventory.py", "--limit", "30"),
    ),
    InventoryCommand(
        QUALITY_DIR / "duplicate_code_inventory.md",
        ("scripts/python_duplicate_code_inventory.py", "--min-lines", "12", "--limit", "40"),
    ),
    InventoryCommand(
        QUALITY_DIR / "architecture_boundary_inventory.md",
        ("scripts/python_architecture_boundary_inventory.py", "--limit", "40"),
    ),
    InventoryCommand(
        QUALITY_DIR / "python_security_inventory.md",
        ("scripts/python_security_inventory.py", "--limit", "30"),
    ),
    InventoryCommand(
        QUALITY_DIR / "api_completeness_inventory.md",
        ("scripts/openapi_completeness_inventory.py", "--limit", "80"),
    ),
    InventoryCommand(
        QUALITY_DIR / "test_taxonomy_inventory.md",
        ("scripts/python_test_taxonomy_inventory.py", "--limit", "30"),
    ),
    InventoryCommand(
        QUALITY_DIR / "observability_readiness_inventory.md",
        ("scripts/python_observability_readiness_inventory.py", "--limit", "30"),
    ),
    InventoryCommand(
        QUALITY_DIR / "documentation_inventory.md",
        ("scripts/python_documentation_inventory.py", "--limit", "40"),
    ),
    InventoryCommand(
        QUALITY_DIR / "router_middleware_thinness_inventory.md",
        ("scripts/python_router_middleware_thinness_inventory.py", "--threshold", "80", "--limit", "50"),
    ),
)


def _run(args: Sequence[str], *, root: Path = ROOT) -> str:
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"{' '.join(args)} failed: {detail}")
    return completed.stdout


def _git_value(args: Sequence[str], *, root: Path = ROOT) -> str:
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


def _python_files(root: Path) -> list[Path]:
    ignored_parts = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}
    return sorted(
        path for path in root.rglob("*.py") if not any(part in ignored_parts for part in path.relative_to(root).parts)
    )


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _collected_tests(*, root: Path = ROOT) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    for line in reversed(combined.splitlines()):
        match = re.search(r"(?P<count>\d+)\s+tests?\s+collected", line)
        if match:
            return f"{match.group('count')} tests"
    return "collection failed" if completed.returncode else "unknown"


def collect_repository_statistics(*, root: Path = ROOT, report_date: str | None = None) -> RepositoryStatistics:
    python_files = _python_files(root)
    largest_files = tuple(
        sorted(
            ((path.relative_to(root).as_posix(), _line_count(path)) for path in python_files),
            key=lambda item: (-item[1], item[0]),
        )[:15]
    )
    workflows = sorted((root / ".github" / "workflows").glob("*.yml"))
    return RepositoryStatistics(
        report_date=report_date or datetime.now(UTC).date().isoformat(),
        branch=_git_value(("branch", "--show-current"), root=root),
        commit=_git_value(("rev-parse", "--short", "HEAD"), root=root),
        python_files=len(python_files),
        package_markers=sum(1 for path in python_files if path.name == "__init__.py"),
        python_loc=sum(_line_count(path) for path in python_files),
        test_modules=len(list((root / "tests").rglob("test_*.py"))),
        collected_tests=_collected_tests(root=root),
        configured_workflows=len(workflows),
        largest_python_files=largest_files,
    )


def run_inventory_commands(
    commands: Iterable[InventoryCommand] = INVENTORY_COMMANDS,
    *,
    output_dir: Path = DEFAULT_INVENTORY_OUTPUT_DIR,
    root: Path = ROOT,
) -> None:
    for command in commands:
        output = _run(command.argv, root=root)
        output_path = output_dir / command.output_path.name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")


def render_baseline_report(stats: RepositoryStatistics) -> str:
    largest_rows = "\n".join(
        f"| {index} | `{path}` | {lines} |" for index, (path, lines) in enumerate(stats.largest_python_files, start=1)
    )
    return f"""# Lotus Performance Enterprise Backend Refactor Baseline

Baseline date: {stats.report_date}
Branch: `{stats.branch}`
Mode: report-only baseline; no new blocking quality gate is introduced by this artifact.

## Purpose

This report records the current measured baseline for the enterprise backend refactor stream before
new modularization work begins. It is generated by `make quality-baseline`, which centralizes the
same report-only inventory commands used by the Quality Baseline Snapshot workflow. Raw scanner
snapshots are written under ignored `output/quality-baseline/`; curated source reports stay under
`quality/`.

## Measured Baseline

| Area | Current value | Evidence |
| --- | ---: | --- |
| Python files | {stats.python_files} | `rg --files -g '*.py'` equivalent excluding local caches |
| Python package markers | {stats.package_markers} | recursive `__init__.py` count |
| Python LOC | {stats.python_loc:,} | recursive `.py` line count |
| Test modules | {stats.test_modules} | `tests/**/test_*.py` |
| Collected tests | {stats.collected_tests} | `python -m pytest --collect-only -q` |
| Configured CI workflows | {stats.configured_workflows} | `.github/workflows/*.yml` |
| Repo-native baseline command | 1 | `make quality-baseline` |

## Largest Python Files By LOC

| Rank | File | Lines |
| ---: | --- | ---: |
{largest_rows}

## Required Inventory Outputs

The baseline command writes these ignored raw scanner snapshots for local review and CI upload:

1. `output/quality-baseline/function_size_inventory.md`
2. `output/quality-baseline/complexity_inventory.md`
3. `output/quality-baseline/dead_code_inventory.md`
4. `output/quality-baseline/dependency_hygiene_report.md`
5. `output/quality-baseline/duplicate_code_inventory.md`
6. `output/quality-baseline/architecture_boundary_inventory.md`
7. `output/quality-baseline/python_security_inventory.md`
8. `output/quality-baseline/api_completeness_inventory.md`
9. `output/quality-baseline/test_taxonomy_inventory.md`
10. `output/quality-baseline/observability_readiness_inventory.md`
11. `output/quality-baseline/documentation_inventory.md`
12. `output/quality-baseline/router_middleware_thinness_inventory.md`

## Initial Refactor Hotspots

The first modular refactor candidates should come from the refreshed function-size,
complexity, architecture, and documentation inventories rather than subjective code reading alone.
Priority should stay on production service modules whose responsibilities can be split without
changing performance calculation behavior, API contracts, or downstream Gateway expectations.
"""


def render_refactor_health_report(stats: RepositoryStatistics) -> str:
    largest_production = next(
        (
            (path, lines)
            for path, lines in stats.largest_python_files
            if path.startswith(("app/", "engine/", "core/", "adapters/"))
        ),
        ("unknown", 0),
    )
    return f"""# Lotus Performance Refactor Health Report

Report date: {stats.report_date}
Branch: `{stats.branch}`
Commit: `{stats.commit}`
Baseline source: `quality/baseline_report.md`
Report mode: report-only scorecard plus existing blocking static-quality gates.

## Purpose

This report is the running before/current health record for the enterprise backend refactor. Update
it whenever a slice changes measured code health, architecture, API governance, security,
observability, tests, or documentation posture.

## Current Baseline Summary

| Metric | Current | Status | Evidence |
| --- | ---: | --- | --- |
| Python files | {stats.python_files} | measured | `quality/baseline_report.md` |
| Python LOC | {stats.python_loc:,} | measured | `quality/baseline_report.md` |
| Test modules | {stats.test_modules} | measured | `quality/baseline_report.md` |
| Collected tests | {stats.collected_tests} | measured | `python -m pytest --collect-only -q` |
| Largest production file LOC | {largest_production[1]} | measured | `{largest_production[0]}` |

## Gate Posture

| Control | Current posture | Evidence |
| --- | --- | --- |
| Complexity | Enforced | `make quality-complexity-gate` |
| Architecture boundaries | Enforced | `make quality-architecture-gate` |
| Router and middleware thinness | Enforced | `make quality-router-thinness-gate` |
| Duplicate production code | Enforced | `make quality-duplicate-code-gate` |
| Observability readiness markers | Enforced | `make quality-observability-readiness-gate` |
| Python security findings | Enforced | `make python-security-gate` |
| API vocabulary and OpenAPI quality | Enforced | `make api-vocabulary-gate`; `make openapi-gate` |
| Repository hygiene | Enforced | `make repository-hygiene-gate` |

## Next Updates

Future commits should update this report when they:

1. split a production hotspot into clearer service, domain, or adapter modules,
2. reduce large-function or large-file pressure,
3. convert a report-only inventory into a deterministic gate,
4. add meaningful tests for calculation, API, security, resilience, or observability behavior,
5. update README, docs, wiki, repo context, or platform context because implementation truth changed.
"""


def render_quality_scorecard(stats: RepositoryStatistics) -> str:
    return f"""# Lotus Performance Refactor Quality Scorecard

Report date: {stats.report_date}
Branch: `{stats.branch}`
Commit: `{stats.commit}`
Baseline source: `quality/baseline_report.md`
Current source: `quality/refactor_health_report.md`
Mode: enterprise backend refactor baseline.

## Scorecard

| Control Area | Current Status | Evidence | Gap | Next Slice |
| --- | --- | --- | --- | --- |
| Architecture | `Partially implemented` | `make quality-architecture-gate`; `quality/architecture_boundary_inventory.md` | Large production service modules remain. | Split the highest-value hotspot without changing API behavior. |
| API and contracts | `Implemented` | `make openapi-gate`; `make api-vocabulary-gate`; `quality/api_completeness_inventory.md` | Spectral is not separately configured. | Preserve zero OpenAPI inventory findings while refactoring. |
| Data and methodology | `Implemented` | methodology docs, RFCs, domain-product contracts, calculation tests | Continue proving methodology behavior through focused regression tests. | Add/refine tests when touched calculation paths move. |
| Security and privacy | `Implemented` | `make python-security-gate`; `make security-audit` | Dependency audit remains separate from baseline generation. | Keep scans green and avoid sensitive logs, labels, and examples. |
| Observability and supportability | `Implemented` | `make quality-observability-readiness-gate`; `quality/observability_readiness_inventory.md` | Runtime proof depth depends on slice scope. | Add focused propagation/metric tests when runtime paths move. |
| Resilience and performance | `Partially implemented` | benchmark tests; runtime and durable recovery docs | Baseline command does not run benchmark suites. | Use targeted benchmarks for query-shape or orchestration changes. |
| Testing | `Implemented` | {stats.collected_tests}; coverage gate | Branch coverage is not configured. | Preserve 99% line coverage and improve touched-slice behavior tests. |
| CI and release evidence | `Implemented` | Feature, PR merge, main releasability, quality baseline workflows | Baseline workflow previously duplicated commands inline. | Keep `make quality-baseline` as the single report refresh surface. |
| Documentation and operations | `Partially implemented` | README, docs, wiki, repo context, quality reports | Docs must keep tracking implementation truth during refactor. | Update docs/wiki/context whenever behavior or ownership changes. |

## Current Measurements

| Metric | Current | Evidence |
| --- | ---: | --- |
| Python files | {stats.python_files} | `quality/baseline_report.md` |
| Python LOC | {stats.python_loc:,} | `quality/baseline_report.md` |
| Test modules | {stats.test_modules} | `quality/baseline_report.md` |
| Collected tests | {stats.collected_tests} | `python -m pytest --collect-only -q` |
| Configured CI workflows | {stats.configured_workflows} | `.github/workflows/*.yml` |

## Method Note

This scorecard uses the Lotus Bank-Buyable Engineering Contract status vocabulary. It does not claim
the whole application is procurement-ready; it records the current implementation-backed posture and
the next measurable slice for the refactor.
"""


def generated_reports(stats: RepositoryStatistics) -> dict[Path, str]:
    return {
        QUALITY_DIR / "baseline_report.md": render_baseline_report(stats),
    }


def write_or_check_reports(stats: RepositoryStatistics, *, write: bool, root: Path = ROOT) -> int:
    failures: list[str] = []
    for absolute_path, content in generated_reports(stats).items():
        output_path = root / absolute_path.relative_to(ROOT)
        if write:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
            continue
        if not output_path.exists() or output_path.read_text(encoding="utf-8") != content:
            failures.append(output_path.relative_to(root).as_posix())
    if failures:
        print("Quality baseline reports are stale. Regenerate with `make quality-baseline`.", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate lotus-performance quality baseline artifacts")
    parser.add_argument("--write", action="store_true", help="Write refreshed report artifacts")
    parser.add_argument("--check", action="store_true", help="Fail when generated report artifacts are stale")
    parser.add_argument(
        "--skip-inventories",
        action="store_true",
        help="Only refresh baseline summary reports, not detailed inventory artifacts",
    )
    args = parser.parse_args()

    if not args.write and not args.check:
        parser.error("choose --write or --check")
    if args.write and args.check:
        parser.error("choose only one of --write or --check")

    if args.write and not args.skip_inventories:
        run_inventory_commands()
    stats = collect_repository_statistics()
    return write_or_check_reports(stats, write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
