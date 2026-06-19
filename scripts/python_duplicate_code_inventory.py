from __future__ import annotations

import argparse
import ast
import hashlib
import numbers
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ("app", "engine", "core", "adapters")


@dataclass(frozen=True)
class DuplicateCodeChunk:
    path: str
    qualified_name: str
    start_line: int
    end_line: int
    lines: int


@dataclass(frozen=True)
class DuplicateCodeHotspot:
    lines: int
    count: int
    chunks: tuple[DuplicateCodeChunk, ...]


class _NameAgnosticNormalizer(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> ast.AST:
        return ast.copy_location(ast.Name(id="identifier", ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.arg:
        return ast.arg(arg="argument", annotation=None)

    def visit_keyword(self, node: ast.keyword) -> ast.keyword:
        return ast.copy_location(ast.keyword(arg="argument", value=self.visit(node.value)), node)

    def visit_alias(self, node: ast.alias) -> ast.alias:
        return ast.alias(name="module", asname="alias" if node.asname else None)

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        normalized = cast(ast.Attribute, self.generic_visit(node))
        normalized.attr = "attribute"
        return normalized

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        value = node.value
        if isinstance(value, bool):
            return ast.Constant(value=True)
        if value is None:
            return ast.Constant(value=None)
        if isinstance(value, str):
            return ast.Constant(value="string")
        if isinstance(value, (numbers.Real, numbers.Complex)):
            return ast.Constant(value=0)
        if isinstance(value, bytes):
            return ast.Constant(value=b"bytes")
        return ast.Constant(value="constant")


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self._parent_stack: list[str] = []
        self.functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._parent_stack.append(node.name)
        self.generic_visit(node)
        self._parent_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append((".".join([*self._parent_stack, node.name]), node))
        self._parent_stack.append(node.name)
        self.generic_visit(node)
        self._parent_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions.append((".".join([*self._parent_stack, node.name]), node))
        self._parent_stack.append(node.name)
        self.generic_visit(node)
        self._parent_stack.pop()


def _python_files(paths: Sequence[str], *, root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = root / raw_path
        if path.is_file() and path.suffix == ".py":
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("*.py"))
    return sorted(files)


def _strip_leading_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if not body:
        return body
    first = body[0]
    if not isinstance(first, ast.Expr):
        return body
    value = first.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return list(body[1:])
    return body


def _normalize_ast(node: ast.AST) -> ast.AST:
    normalized = _NameAgnosticNormalizer().visit(ast.fix_missing_locations(ast.parse(ast.unparse(node))))
    return ast.fix_missing_locations(normalized)


def _function_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, int]:
    body = _strip_leading_docstring(list(node.body))
    if not body:
        return "", 0
    normalized_body = _normalize_ast(ast.Module(body=body, type_ignores=[]))
    normalized_dump = ast.dump(normalized_body, annotate_fields=False, include_attributes=False)
    start_line = min((stmt.lineno for stmt in body))
    end_line = max((stmt.end_lineno or stmt.lineno for stmt in body))
    return hashlib.sha1(normalized_dump.encode("utf-8")).hexdigest(), end_line - start_line + 1


def collect_duplicate_code_hotspots(
    paths: Sequence[str] = DEFAULT_PATHS,
    *,
    min_lines: int = 12,
    root: Path = ROOT,
) -> list[DuplicateCodeHotspot]:
    groups: dict[str, list[DuplicateCodeChunk]] = defaultdict(list)

    for path in _python_files(paths, root=root):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        relative_path = path.relative_to(root).as_posix()
        collector = _FunctionCollector(relative_path)
        collector.visit(tree)
        for qualified_name, function in collector.functions:
            body = _strip_leading_docstring(list(function.body))
            if len(body) < min_lines:
                continue
            fingerprint, lines = _function_fingerprint(function)
            if not fingerprint:
                continue
            groups[fingerprint].append(
                DuplicateCodeChunk(
                    path=relative_path,
                    qualified_name=qualified_name,
                    start_line=body[0].lineno,
                    end_line=body[-1].end_lineno or body[-1].lineno,
                    lines=lines,
                )
            )

    hotspots: list[DuplicateCodeHotspot] = []
    for chunks in groups.values():
        if len(chunks) < 2:
            continue
        chunks_sorted = sorted(chunks, key=lambda chunk: (chunk.path, chunk.start_line))
        hotspots.append(
            DuplicateCodeHotspot(lines=chunks[0].lines, count=len(chunks_sorted), chunks=tuple(chunks_sorted))
        )

    return sorted(
        hotspots,
        key=lambda hotspot: (hotspot.count, hotspot.lines),
        reverse=True,
    )


def render_markdown(hotspots: Sequence[DuplicateCodeHotspot], *, limit: int) -> str:
    total_groups = len(hotspots)
    total_functions = sum(hotspot.count for hotspot in hotspots)
    duplicated_lines = sum(hotspot.lines * hotspot.count for hotspot in hotspots)
    max_group = max((hotspot.count for hotspot in hotspots), default=0)
    max_lines = max((hotspot.lines for hotspot in hotspots), default=0)
    files = {chunk.path for hotspot in hotspots for chunk in hotspot.chunks}

    lines: list[str] = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Duplicate hotspot groups | {total_groups} |",
        f"| Duplicate functions/methods | {total_functions} |",
        f"| Files participating in duplication | {len(files)} |",
        f"| Total duplicated LOC (reported members) | {duplicated_lines} |",
        f"| Max duplicate count in group | {max_group} |",
        f"| Max LOC in duplicate group | {max_lines} |",
        "",
        "## Duplicate Hotspots",
        "",
        "| Rank | Group count | Body LOC | Instances | Locations |",
        "| ---: | ---: | ---: | ---: | --- |",
    ]

    for index, hotspot in enumerate(hotspots[:limit], start=1):
        locations = "<br>".join(f"`{chunk.path}:{chunk.start_line}-{chunk.end_line}`" for chunk in hotspot.chunks)
        lines.append(f"| {index} | {hotspot.count} | {hotspot.lines} | {hotspot.count} | {locations} |")

    return "\n".join(lines)


def duplicate_code_threshold_violations(
    hotspots: Sequence[DuplicateCodeHotspot],
    *,
    max_groups: int | None = None,
) -> list[str]:
    if max_groups is None or len(hotspots) <= max_groups:
        return []
    return [
        f"Duplicate code gate failed: duplicate hotspot groups {len(hotspots)} exceed configured maximum {max_groups}."
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory duplicate production Python code blocks")
    parser.add_argument("--path", action="append", dest="paths", help="Path to scan relative to the repository root")
    parser.add_argument(
        "--min-lines",
        type=int,
        default=12,
        help="Minimum body line count for a function to participate in duplicate detection",
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum hotspot rows in output")
    parser.add_argument(
        "--max-groups",
        type=int,
        default=None,
        help="Fail when duplicate hotspot groups exceed this maximum",
    )
    args = parser.parse_args()

    paths = tuple(args.paths or DEFAULT_PATHS)
    hotspots = collect_duplicate_code_hotspots(paths, min_lines=args.min_lines)
    print(render_markdown(hotspots, limit=args.limit))
    violations = duplicate_code_threshold_violations(hotspots, max_groups=args.max_groups)
    for violation in violations:
        print(f"\nERROR: {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
