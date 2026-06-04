from __future__ import annotations

import argparse
import ast
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ("app/api/endpoints", "app")
DEFAULT_THRESHOLD = 80
ROUTER_PREFIX = "app/api/endpoints/"
MIDDLEWARE_KEYWORDS = ("middleware",)


@dataclass(frozen=True)
class ThinnessFinding:
    path: str
    qualified_name: str
    start_line: int
    end_line: int
    lines: int
    kind: str


class _FunctionVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self._parent_stack: list[str] = []
        self.functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._parent_stack.append(node.name)
        self.generic_visit(node)
        self._parent_stack.pop()

    def _qualified_name(self, node_name: str) -> str:
        if not self._parent_stack:
            return node_name
        return ".".join([*self._parent_stack, node_name])

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append((self._qualified_name(node.name), node))
        self._parent_stack.append(node.name)
        self.generic_visit(node)
        self._parent_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions.append((self._qualified_name(node.name), node))
        self._parent_stack.append(node.name)
        self.generic_visit(node)
        self._parent_stack.pop()


def _python_files(paths: Sequence[str], *, root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = root / raw_path
        if path.is_file() and path.suffix == ".py":
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(path)
        elif path.is_dir():
            for file_path in path.rglob("*.py"):
                resolved = file_path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                files.append(file_path)
    return sorted(files)


def _is_router(path: str) -> bool:
    return path.startswith(ROUTER_PREFIX)


def _is_middleware(path: str) -> bool:
    lower_path = path.lower()
    return "middleware" in lower_path


def _function_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    start_line = node.lineno
    end_line = node.end_lineno or node.lineno
    return end_line - start_line + 1


def collect_thinness_findings(
    paths: Sequence[str] = DEFAULT_PATHS,
    *,
    root: Path = ROOT,
    threshold: int = DEFAULT_THRESHOLD,
) -> list[ThinnessFinding]:
    findings: list[ThinnessFinding] = []
    for path in _python_files(paths, root=root):
        relative_path = path.relative_to(root).as_posix()
        node = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
        visitor = _FunctionVisitor(relative_path)
        visitor.visit(node)

        for qualified_name, function_node in visitor.functions:
            lines = _function_lines(function_node)
            if lines <= threshold:
                continue
            if _is_router(relative_path):
                kind = "router"
            elif _is_middleware(relative_path):
                kind = "middleware"
            else:
                continue
            findings.append(
                ThinnessFinding(
                    path=relative_path,
                    qualified_name=qualified_name,
                    start_line=function_node.lineno,
                    end_line=function_node.end_lineno or function_node.lineno,
                    lines=lines,
                    kind=kind,
                )
            )
    return sorted(findings, key=lambda item: (-item.lines, item.kind, item.path, item.start_line))


def render_markdown(findings: Sequence[ThinnessFinding], *, limit: int) -> str:
    kind_counts = Counter(finding.kind for finding in findings)
    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Router and middleware oversized function findings | {len(findings)} |",
        f"| Oversized router functions | {kind_counts.get('router', 0)} |",
        f"| Oversized middleware functions | {kind_counts.get('middleware', 0)} |",
        "",
        "## Findings",
        "",
        "| Rank | Kind | File | Function | Lines |",
        "| ---: | --- | --- | --- | ---: |",
    ]
    for index, finding in enumerate(findings[:limit], start=1):
        lines.append(
            f"| {index} | {finding.kind} | `{finding.path}:{finding.start_line}` | "
            f"`{finding.qualified_name}` | {finding.lines} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory oversized router and middleware functions")
    parser.add_argument("--path", action="append", dest="paths", help="Path to scan relative to the repository root")
    parser.add_argument(
        "--threshold", type=int, default=DEFAULT_THRESHOLD, help="Line threshold to flag oversized functions"
    )
    parser.add_argument("--limit", type=int, default=40, help="Maximum number of findings to report")
    args = parser.parse_args()

    paths = tuple(args.paths or DEFAULT_PATHS)
    findings = collect_thinness_findings(paths, threshold=args.threshold)
    print(render_markdown(findings, limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
