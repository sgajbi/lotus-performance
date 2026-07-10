from __future__ import annotations

import argparse
import ast
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ("app/api/endpoints", "engine", "core", "app/services")

_ROUTER_DISALLOWED_PREFIXES = (
    "adapters",
    "core",
    "engine",
    "httpx",
    "kafka",
    "psycopg",
    "redis",
    "sqlalchemy",
)
_DOMAIN_DISALLOWED_PREFIXES = ("adapters", "app", "fastapi", "starlette")
_APPLICATION_CONCRETE_STORE_MODULES = (
    "app.services.async_result_store",
    "app.services.compute_job_store",
    "app.services.composite_metadata_store",
    "app.services.execution_registry",
    "app.services.lineage_metadata_store",
)
_ENFORCED_RULES = frozenset(
    {
        "ROUTER_DIRECT_BOUNDARY_IMPORT",
        "DOMAIN_INFRA_OR_FRAMEWORK_IMPORT",
    }
)


@dataclass(frozen=True)
class ArchitectureBoundaryFinding:
    path: str
    line: int
    imported_module: str
    rule: str
    description: str
    enforced: bool = True


def _module_matches(imported_module: str, prefixes: Sequence[str]) -> bool:
    return any(imported_module == prefix or imported_module.startswith(f"{prefix}.") for prefix in prefixes)


def classify_import(path: str, imported_module: str) -> tuple[str, str] | None:
    if path.startswith("app/api/endpoints/") and _module_matches(imported_module, _ROUTER_DISALLOWED_PREFIXES):
        return (
            "ROUTER_DIRECT_BOUNDARY_IMPORT",
            "API routers should route through app services/use cases instead of direct domain, engine, or infrastructure imports.",
        )
    if (path.startswith("engine/") or path.startswith("core/")) and _module_matches(
        imported_module, _DOMAIN_DISALLOWED_PREFIXES
    ):
        return (
            "DOMAIN_INFRA_OR_FRAMEWORK_IMPORT",
            "Engine/core modules should stay independent from application DTOs, adapters, and web framework imports.",
        )
    if path.startswith("app/services/") and _module_matches(imported_module, _APPLICATION_CONCRETE_STORE_MODULES):
        return (
            "APPLICATION_SERVICE_CONCRETE_STORE_IMPORT",
            "Application services should depend on ports/interfaces instead of concrete durable store modules.",
        )
    return None


def is_enforced_rule(rule: str) -> bool:
    return rule in _ENFORCED_RULES


def _python_files(paths: Sequence[str], *, root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = root / raw_path
        if path.is_file() and path.suffix == ".py":
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("*.py"))
    return sorted(files)


def _imported_modules(tree: ast.AST) -> Iterable[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def collect_architecture_findings(
    paths: Sequence[str] = DEFAULT_PATHS,
    *,
    root: Path = ROOT,
) -> list[ArchitectureBoundaryFinding]:
    findings: list[ArchitectureBoundaryFinding] = []
    for path in _python_files(paths, root=root):
        relative_path = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
        for line, imported_module in _imported_modules(tree):
            classification = classify_import(relative_path, imported_module)
            if classification is None:
                continue
            rule, description = classification
            findings.append(
                ArchitectureBoundaryFinding(
                    path=relative_path,
                    line=line,
                    imported_module=imported_module,
                    rule=rule,
                    description=description,
                    enforced=is_enforced_rule(rule),
                )
            )
    return sorted(findings, key=lambda item: (item.rule, item.path, item.line, item.imported_module))


def render_markdown(findings: Sequence[ArchitectureBoundaryFinding], *, limit: int) -> str:
    rule_counts = Counter(finding.rule for finding in findings)
    area_counts = Counter(
        "API routers"
        if finding.path.startswith("app/api/endpoints/")
        else "Engine"
        if finding.path.startswith("engine/")
        else "Core"
        if finding.path.startswith("core/")
        else "Application services"
        if finding.path.startswith("app/services/")
        else "Other"
        for finding in findings
    )

    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Architecture boundary findings | {len(findings)} |",
        f"| Enforced findings | {sum(1 for finding in findings if finding.enforced)} |",
        f"| Report-only findings | {sum(1 for finding in findings if not finding.enforced)} |",
        f"| Distinct rules | {len(rule_counts)} |",
        f"| Distinct files | {len({finding.path for finding in findings})} |",
        "",
        "## Findings By Rule",
        "",
        "| Rule | Count |",
        "| --- | ---: |",
    ]
    for rule, count in sorted(rule_counts.items()):
        lines.append(f"| `{rule}` | {count} |")

    lines.extend(["", "## Findings By Area", "", "| Area | Count |", "| --- | ---: |"])
    for area, count in sorted(area_counts.items()):
        lines.append(f"| {area} | {count} |")

    lines.extend(
        [
            "",
            "## Findings",
            "",
            "| Rank | Rule | Posture | File | Import | Description |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for index, finding in enumerate(findings[:limit], start=1):
        posture = "enforced" if finding.enforced else "report-only"
        lines.append(
            f"| {index} | `{finding.rule}` | {posture} | `{finding.path}:{finding.line}` | "
            f"`{finding.imported_module}` | {finding.description} |"
        )
    return "\n".join(lines)


def max_findings_violation(findings_count: int, max_findings: int | None) -> str | None:
    if max_findings is None or findings_count <= max_findings:
        return None
    return f"Architecture boundary gate failed: {findings_count} finding(s) exceed configured maximum {max_findings}."


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Lotus architecture-boundary import findings")
    parser.add_argument("--path", action="append", dest="paths", help="Path to scan relative to the repository root")
    parser.add_argument("--limit", type=int, default=40, help="Maximum rows in the findings table")
    parser.add_argument(
        "--max-findings",
        type=int,
        help="Fail when architecture-boundary finding count exceeds this value",
    )
    args = parser.parse_args()

    paths = tuple(args.paths or DEFAULT_PATHS)
    findings = collect_architecture_findings(paths)
    print(render_markdown(findings, limit=args.limit))
    enforced_findings_count = sum(1 for finding in findings if finding.enforced)
    violation = max_findings_violation(enforced_findings_count, args.max_findings)
    if violation is not None:
        print(violation)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
