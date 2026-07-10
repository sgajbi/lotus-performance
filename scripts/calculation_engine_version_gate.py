from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app"
ALLOWED_APP_VERSION_FILES = {
    Path("app/core/config.py"),
    Path("app/services/build_metadata_service.py"),
    Path("app/services/calculation_engine_version.py"),
}
FORBIDDEN_LITERAL_TOKENS = {"returns-series-v1"}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    code: str
    detail: str


def _is_app_version_attribute(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "APP_VERSION"


def _literal_token(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in FORBIDDEN_LITERAL_TOKENS:
        return node.value
    return None


class CalculationEngineVersionVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[Finding] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if _is_app_version_attribute(node) and self.path not in ALLOWED_APP_VERSION_FILES:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    code="APP_VERSION_USED_FOR_CALCULATION_IDENTITY",
                    detail="Production calculation code must use calculation_engine_version(...), not APP_VERSION.",
                )
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        token = _literal_token(node)
        if token is not None:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    code="HARDCODED_CALCULATION_ENGINE_VERSION",
                    detail=f"Hard-coded calculation hash version token {token!r} is not allowed in production code.",
                )
            )


def collect_findings(paths: list[Path] | None = None) -> list[Finding]:
    python_files = paths or sorted(APP_PATH.rglob("*.py"))
    findings: list[Finding] = []
    for file_path in python_files:
        try:
            relative_path = file_path.relative_to(ROOT)
        except ValueError:
            relative_path = file_path
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(relative_path))
        visitor = CalculationEngineVersionVisitor(relative_path)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    return findings


def main() -> int:
    findings = collect_findings()
    if findings:
        for finding in findings:
            print(f"{finding.path}:{finding.line}: {finding.code}: {finding.detail}")
        return 1
    print("Calculation engine version gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
