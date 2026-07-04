from __future__ import annotations

import os
import shutil
import subprocess
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
GENERATED_RUNTIME_ROOT_NAMES = frozenset(
    {
        "artifacts",
        "lineage_data",
        "output",
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
LOCAL_FILE_PREFIXES = (".coverage.",)
LOCAL_GENERATED_SUFFIXES = frozenset(
    {
        ".db",
        ".db-journal",
        ".db-shm",
        ".db-wal",
        ".log",
        ".sqlite",
        ".sqlite-journal",
        ".sqlite-shm",
        ".sqlite-wal",
        ".sqlite3",
        ".sqlite3-journal",
        ".sqlite3-shm",
        ".sqlite3-wal",
    }
)
PROTECTED_SOURCE_ROOT_NAMES = frozenset(
    {
        "contracts",
        "docs",
        "quality",
        "wiki",
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


def _normalised_relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _tracked_relative_paths(root: Path) -> frozenset[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
            text=False,
        )
    except (OSError, subprocess.CalledProcessError):
        return frozenset()
    return frozenset(path.decode("utf-8") for path in result.stdout.split(b"\0") if path)


def _has_tracked_content(path: Path, root: Path, tracked_paths: frozenset[str]) -> bool:
    relative_path = _normalised_relative_path(path, root)
    prefix = f"{relative_path}/"
    return any(tracked_path == relative_path or tracked_path.startswith(prefix) for tracked_path in tracked_paths)


def _is_protected_source_path(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    return bool(relative_parts) and relative_parts[0] in PROTECTED_SOURCE_ROOT_NAMES


def _is_local_generated_file(path: Path, root: Path, tracked_paths: frozenset[str]) -> bool:
    if _normalised_relative_path(path, root) in tracked_paths:
        return False
    if path.name in LOCAL_FILE_NAMES or path.name.startswith(LOCAL_FILE_PREFIXES):
        return True
    if _is_protected_source_path(path, root):
        return False
    return bool(set(path.suffixes) & LOCAL_GENERATED_SUFFIXES)


def build_cleanup_plan(root: Path = ROOT) -> CleanupPlan:
    root = root.resolve()
    tracked_paths = _tracked_relative_paths(root)
    directories: list[Path] = []
    files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(dirpath)
        kept_dirnames: list[str] = []
        for dirname in sorted(dirnames):
            child = current / dirname
            if _is_pruned(child, root):
                continue
            if (
                current == root
                and dirname in GENERATED_RUNTIME_ROOT_NAMES
                and not child.is_symlink()
                and not _has_tracked_content(child, root, tracked_paths)
            ):
                directories.append(child)
                continue
            if dirname in CACHE_DIR_NAMES | BUILD_DIR_NAMES:
                directories.append(child)
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in sorted(filenames):
            path = current / filename
            if _is_local_generated_file(path, root, tracked_paths):
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
