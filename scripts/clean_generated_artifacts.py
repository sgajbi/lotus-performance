from __future__ import annotations

import os
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
        "venv",
        "node_modules",
    }
)


@dataclass(frozen=True)
class CleanupPlan:
    directories: tuple[Path, ...]
    files: tuple[Path, ...]


def _is_pruned(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    return bool(set(relative_parts) & PRUNED_DIR_NAMES) or (path / "pyvenv.cfg").is_file()


def build_cleanup_plan(root: Path = ROOT) -> CleanupPlan:
    root = root.resolve()
    directories: list[Path] = []
    files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(dirpath)
        kept_dirnames: list[str] = []
        for dirname in sorted(dirnames):
            child = current / dirname
            if _is_pruned(child, root):
                continue
            if dirname in CACHE_DIR_NAMES | BUILD_DIR_NAMES:
                directories.append(child)
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in sorted(filenames):
            path = current / filename
            if path.name in LOCAL_FILE_NAMES:
                files.append(path)

    return CleanupPlan(directories=tuple(sorted(directories)), files=tuple(sorted(files)))


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
