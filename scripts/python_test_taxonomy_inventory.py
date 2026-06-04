from __future__ import annotations

import argparse
import ast
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ("tests",)


@dataclass(frozen=True)
class TestModuleInventory:
    path: str
    suite: str
    test_count: int
    families: tuple[str, ...]


def _normalize_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        parts = path.parts
        if "tests" in parts:
            return Path(*parts[parts.index("tests") :]).as_posix()
        return path.as_posix()


def _suite_for_path(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "tests" and parts[1] in {"unit", "integration", "e2e", "benchmarks"}:
        return parts[1]
    return "other"


def _families_for_path(path: str) -> tuple[str, ...]:
    lower_path = path.lower()
    families: set[str] = set()
    if lower_path.startswith("tests/integration/") or lower_path.startswith("tests/e2e/"):
        families.add("api_or_runtime")
    if any(token in lower_path for token in ("api", "endpoint", "openapi", "router")):
        families.add("api_or_runtime")
    if any(token in lower_path for token in ("contract", "vocabulary", "domain_data_product", "trust_telemetry")):
        families.add("contract_or_governance")
    if lower_path.startswith("tests/unit/docs/") or "docs_contract" in lower_path:
        families.add("contract_or_governance")
    if lower_path.startswith("tests/unit/scripts/") or any(
        token in lower_path for token in ("security", "monetary", "dependency", "quality", "architecture")
    ):
        families.add("quality_or_security")
    if any(token in lower_path for token in ("metric", "metrics", "logging", "correlation", "health", "readiness")):
        families.add("observability_or_readiness")
    if any(token in lower_path for token in ("engine", "calculation", "twr", "mwr", "attribution", "contribution")):
        families.add("analytics_domain")
    return tuple(sorted(families or {"uncategorized"}))


def _count_test_functions(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_")
    )


def collect_test_modules(paths: Sequence[str] = DEFAULT_PATHS) -> list[TestModuleInventory]:
    modules: list[TestModuleInventory] = []
    for path_name in paths:
        root = (ROOT / path_name).resolve()
        candidates = [root] if root.is_file() else sorted(root.rglob("test_*.py"))
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix != ".py":
                continue
            relative_path = _normalize_path(candidate)
            modules.append(
                TestModuleInventory(
                    path=relative_path,
                    suite=_suite_for_path(relative_path),
                    test_count=_count_test_functions(candidate),
                    families=_families_for_path(relative_path),
                )
            )
    return sorted(modules, key=lambda module: module.path)


def _count_by_suite(modules: Iterable[TestModuleInventory]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for module in modules:
        counts[module.suite] += module.test_count
    return counts


def _count_modules_by_suite(modules: Iterable[TestModuleInventory]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for module in modules:
        counts[module.suite] += 1
    return counts


def _count_by_family(modules: Iterable[TestModuleInventory]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for module in modules:
        for family in module.families:
            counts[family] += module.test_count
    return counts


def render_markdown(modules: Sequence[TestModuleInventory], *, limit: int) -> str:
    suite_counts = _count_by_suite(modules)
    suite_module_counts = _count_modules_by_suite(modules)
    family_counts = _count_by_family(modules)
    total_tests = sum(module.test_count for module in modules)
    api_or_runtime_tests = family_counts["api_or_runtime"]
    contract_or_governance_tests = family_counts["contract_or_governance"]

    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Test modules inventoried | {len(modules)} |",
        f"| Test functions inventoried | {total_tests} |",
        f"| Integration/API/runtime test functions | {api_or_runtime_tests} |",
        f"| Contract/governance test functions | {contract_or_governance_tests} |",
        "",
        "## Test Functions By Suite",
        "",
        "| Suite | Modules | Test functions |",
        "| --- | ---: | ---: |",
    ]
    for suite in sorted(suite_module_counts):
        lines.append(f"| {suite} | {suite_module_counts[suite]} | {suite_counts[suite]} |")

    lines.extend(["", "## Test Functions By Family", "", "| Family | Test functions |", "| --- | ---: |"])
    for family, count in sorted(family_counts.items()):
        lines.append(f"| {family} | {count} |")

    lines.extend(
        [
            "",
            "## Largest Test Modules",
            "",
            "| Rank | Module | Suite | Test functions | Families |",
            "| ---: | --- | --- | ---: | --- |",
        ]
    )
    largest_modules = sorted(modules, key=lambda module: (-module.test_count, module.path))
    for index, module in enumerate(largest_modules[:limit], start=1):
        lines.append(
            f"| {index} | `{module.path}` | {module.suite} | {module.test_count} | {', '.join(module.families)} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Lotus performance test taxonomy")
    parser.add_argument("--path", action="append", dest="paths", help="Path to scan relative to the repository root")
    parser.add_argument("--limit", type=int, default=30, help="Maximum largest-module rows to render")
    args = parser.parse_args()

    paths = tuple(args.paths or DEFAULT_PATHS)
    print(render_markdown(collect_test_modules(paths), limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
