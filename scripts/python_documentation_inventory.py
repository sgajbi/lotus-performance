from __future__ import annotations

import argparse
import ast
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PATHS = ("app", "engine", "core", "adapters", "common")
README_MARKERS = (
    "Purpose And Scope",
    "Current Operational Posture",
    "Enterprise Readiness Evidence",
    "Architecture At A Glance",
    "Quick Start",
    "Common Commands",
    "/openapi.json",
    "This is not a blanket production certification for every client environment.",
)
API_CATALOG_FILES = (
    "docs/guides/api_reference.md",
    "docs/guides/complete_service_reference.md",
    "wiki/API-Surface.md",
    "quality/api_completeness_inventory.md",
)
MAJOR_PACK_READMES = (
    "app/README.md",
    "engine/README.md",
    "core/README.md",
    "adapters/README.md",
    "common/README.md",
    "docs/README.md",
    "contracts/README.md",
    "quality/README.md",
    "scripts/README.md",
    "tests/README.md",
    "wiki/README.md",
    "monitoring/README.md",
)


@dataclass(frozen=True)
class DocumentationInventory:
    readme_markers_present: int
    readme_markers_expected: int
    wiki_pages: int
    markdown_files: int
    guide_files: int
    methodology_files: int
    operations_files: int
    rfc_files: int
    certification_files: int
    api_catalog_files_present: int
    api_catalog_files_expected: int
    major_pack_readmes_present: int
    major_pack_readmes_expected: int
    docs_test_functions: int
    public_definitions: int
    public_definitions_missing_docstring: int


@dataclass(frozen=True)
class PublicDefinitionDocstringGap:
    path: str
    line: int
    name: str
    kind: str


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _markdown_files() -> list[Path]:
    roots = [ROOT / "docs", ROOT / "wiki"]
    files = [ROOT / "README.md"]
    for root in roots:
        if root.exists():
            files.extend(sorted(root.rglob("*.md")))
    return sorted(path for path in files if path.is_file())


def _docs_test_function_count() -> int:
    tests_root = ROOT / "tests" / "unit" / "docs"
    count = 0
    for path in sorted(tests_root.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_")
        )
    return count


PublicDefinitionNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _public_definition_nodes(tree: ast.AST) -> Iterable[PublicDefinitionNode]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and not node.name.startswith("_"):
            yield node


def collect_public_docstring_gaps(paths: Sequence[str] = PRODUCTION_PATHS) -> list[PublicDefinitionDocstringGap]:
    gaps: list[PublicDefinitionDocstringGap] = []
    for path_name in paths:
        root = ROOT / path_name
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in candidates:
            if not path.is_file() or path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in _public_definition_nodes(tree):
                if ast.get_docstring(node):
                    continue
                gaps.append(
                    PublicDefinitionDocstringGap(
                        path=_relative(path),
                        line=node.lineno,
                        name=node.name,
                        kind=type(node).__name__,
                    )
                )
    return sorted(gaps, key=lambda gap: (gap.path, gap.line, gap.name))


def _public_definition_count(paths: Sequence[str] = PRODUCTION_PATHS) -> int:
    count = 0
    for path_name in paths:
        root = ROOT / path_name
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in candidates:
            if not path.is_file() or path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            count += sum(1 for _node in _public_definition_nodes(tree))
    return count


def collect_documentation_inventory() -> DocumentationInventory:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    markdown_files = _markdown_files()
    path_counts = Counter(
        _relative(path).split("/")[1] for path in markdown_files if _relative(path).startswith("docs/")
    )
    certification_files = [
        path
        for path in markdown_files
        if _relative(path).startswith("docs/technical/") and "certification" in path.name
    ]
    api_catalog_present = sum(1 for path_name in API_CATALOG_FILES if (ROOT / path_name).is_file())
    major_pack_readmes_present = sum(1 for path_name in MAJOR_PACK_READMES if (ROOT / path_name).is_file())
    public_definitions = _public_definition_count()
    docstring_gaps = collect_public_docstring_gaps()

    return DocumentationInventory(
        readme_markers_present=sum(1 for marker in README_MARKERS if marker in readme),
        readme_markers_expected=len(README_MARKERS),
        wiki_pages=len([path for path in markdown_files if _relative(path).startswith("wiki/")]),
        markdown_files=len(markdown_files),
        guide_files=path_counts["guides"],
        methodology_files=path_counts["methodologies"],
        operations_files=path_counts["operations"],
        rfc_files=path_counts["RFCs"],
        certification_files=len(certification_files),
        api_catalog_files_present=api_catalog_present,
        api_catalog_files_expected=len(API_CATALOG_FILES),
        major_pack_readmes_present=major_pack_readmes_present,
        major_pack_readmes_expected=len(MAJOR_PACK_READMES),
        docs_test_functions=_docs_test_function_count(),
        public_definitions=public_definitions,
        public_definitions_missing_docstring=len(docstring_gaps),
    )


def _coverage_percent(inventory: DocumentationInventory) -> float:
    if inventory.public_definitions == 0:
        return 100.0
    documented = inventory.public_definitions - inventory.public_definitions_missing_docstring
    return round((documented / inventory.public_definitions) * 100, 2)


def render_markdown(
    inventory: DocumentationInventory,
    docstring_gaps: Iterable[PublicDefinitionDocstringGap],
    *,
    limit: int,
) -> str:
    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| README required markers present | {inventory.readme_markers_present} |",
        f"| README required markers expected | {inventory.readme_markers_expected} |",
        f"| Wiki source pages | {inventory.wiki_pages} |",
        f"| Markdown documentation files | {inventory.markdown_files} |",
        f"| API catalog files present | {inventory.api_catalog_files_present} |",
        f"| API catalog files expected | {inventory.api_catalog_files_expected} |",
        f"| Major pack README files present | {inventory.major_pack_readmes_present} |",
        f"| Major pack README files expected | {inventory.major_pack_readmes_expected} |",
        f"| Docs regression test functions | {inventory.docs_test_functions} |",
        f"| Public definitions scanned | {inventory.public_definitions} |",
        f"| Public definitions missing docstrings | {inventory.public_definitions_missing_docstring} |",
        f"| Public definition docstring coverage percent | {_coverage_percent(inventory):.2f} |",
        "",
        "## Markdown Files By Family",
        "",
        "| Family | Files |",
        "| --- | ---: |",
        f"| guides | {inventory.guide_files} |",
        f"| methodologies | {inventory.methodology_files} |",
        f"| operations | {inventory.operations_files} |",
        f"| RFCs | {inventory.rfc_files} |",
        f"| endpoint certification | {inventory.certification_files} |",
        "",
        "## Public Docstring Gaps",
        "",
        "| Rank | File | Line | Kind | Name |",
        "| ---: | --- | ---: | --- | --- |",
    ]
    gaps = list(docstring_gaps)
    for index, gap in enumerate(gaps[:limit], start=1):
        lines.append(f"| {index} | `{gap.path}` | {gap.line} | `{gap.kind}` | `{gap.name}` |")
    if not gaps:
        lines.append("| none | none | 0 | none | none |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Lotus performance documentation readiness")
    parser.add_argument("--limit", type=int, default=40, help="Maximum docstring-gap rows to render")
    args = parser.parse_args()

    inventory = collect_documentation_inventory()
    print(render_markdown(inventory, collect_public_docstring_gaps(), limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
