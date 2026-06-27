from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CACHE_DIR_NAMES = frozenset(
    {
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
    }
)
BUILD_DIR_NAMES = frozenset(
    {
        "build",
        "dist",
        "htmlcov",
    }
)
LOCAL_FILE_NAMES = frozenset(
    {
        ".coverage",
        ".coverage.unit",
        ".coverage.integration",
        ".coverage.e2e",
        "coverage.xml",
    }
)
PRUNED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
    }
)


@dataclass(frozen=True)
class CleanupPlan:
    directories: tuple[Path, ...]
    files: tuple[Path, ...]


def _is_pruned(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    return bool(set(relative_parts) & PRUNED_DIR_NAMES)


def build_cleanup_plan(root: Path = ROOT) -> CleanupPlan:
    root = root.resolve()
    directories: list[Path] = []
    files: list[Path] = []

    for path in sorted(root.rglob("*")):
        if _is_pruned(path, root):
            continue
        if path.is_dir() and path.name in CACHE_DIR_NAMES | BUILD_DIR_NAMES:
            directories.append(path)
        elif path.is_file() and path.name in LOCAL_FILE_NAMES:
            files.append(path)

    return CleanupPlan(directories=tuple(directories), files=tuple(files))


def clean_generated_artifacts(root: Path = ROOT) -> CleanupPlan:
    plan = build_cleanup_plan(root)
    for directory in plan.directories:
        shutil.rmtree(directory, ignore_errors=True)
    for file_path in plan.files:
        file_path.unlink(missing_ok=True)
    return plan


def main() -> int:
    plan = clean_generated_artifacts()
    print(f"Removed {len(plan.directories)} generated directories and {len(plan.files)} local artifact files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
