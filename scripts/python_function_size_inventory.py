from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ("app", "engine", "core", "adapters")


@dataclass(frozen=True)
class FunctionSize:
    path: str
    qualified_name: str
    start_line: int
    end_line: int
    lines: int


class _FunctionSizeVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self._parents: list[str] = []
        self.functions: list[FunctionSize] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._parents.append(node.name)
        self.generic_visit(node)
        self._parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)
        self._parents.append(node.name)
        self.generic_visit(node)
        self._parents.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)
        self._parents.append(node.name)
        self.generic_visit(node)
        self._parents.pop()

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        end_line = node.end_lineno or node.lineno
        qualified_name = ".".join([*self._parents, node.name])
        self.functions.append(
            FunctionSize(
                path=self.path,
                qualified_name=qualified_name,
                start_line=node.lineno,
                end_line=end_line,
                lines=end_line - node.lineno + 1,
            )
        )


def _python_files(paths: Sequence[str], *, root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = root / raw_path
        if path.is_file() and path.suffix == ".py":
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("*.py"))
    return sorted(files)


def collect_function_sizes(paths: Sequence[str] = DEFAULT_PATHS, *, root: Path = ROOT) -> list[FunctionSize]:
    functions: list[FunctionSize] = []
    for path in _python_files(paths, root=root):
        relative_path = path.relative_to(root).as_posix()
        visitor = _FunctionSizeVisitor(relative_path)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=relative_path))
        functions.extend(visitor.functions)
    return sorted(functions, key=lambda item: (-item.lines, item.path, item.qualified_name, item.start_line))


def render_markdown(functions: Iterable[FunctionSize]) -> str:
    rows = ["| Rank | Function | File | Lines |", "| ---: | --- | --- | ---: |"]
    for index, function in enumerate(functions, start=1):
        rows.append(
            f"| {index} | `{function.qualified_name}` | `{function.path}:{function.start_line}` | {function.lines} |"
        )
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory largest Python functions by source-line span")
    parser.add_argument("--path", action="append", dest="paths", help="Path to scan relative to the repository root")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of functions to report")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown", help="Output format")
    args = parser.parse_args()

    paths = tuple(args.paths or DEFAULT_PATHS)
    functions = collect_function_sizes(paths)[: args.limit]
    if args.format == "json":
        print(json.dumps([asdict(function) for function in functions], indent=2))
    else:
        print(render_markdown(functions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
