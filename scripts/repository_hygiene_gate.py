from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROHIBITED_EXACT_PATHS = {
    ".coverage",
    ".env",
    "coverage.xml",
}
PROHIBITED_PATH_PARTS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "venv",
}
PROHIBITED_SUFFIXES = {
    ".db",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".egg-info",
    ".log",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite-journal",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".sqlite3-journal",
    ".sqlite3-shm",
    ".sqlite3-wal",
}


def _tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=False,
    )
    return [path.decode("utf-8") for path in result.stdout.split(b"\0") if path]


def _normalise(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _has_prohibited_path_part(parts: set[str]) -> bool:
    return bool(parts & PROHIBITED_PATH_PARTS) or any(part.endswith(".egg-info") for part in parts)


def find_repository_hygiene_violations(tracked_paths: list[str]) -> list[str]:
    violations: list[str] = []
    for tracked_path in tracked_paths:
        normalised = _normalise(tracked_path)
        name = Path(normalised).name
        parts = set(normalised.split("/"))
        suffixes = Path(normalised).suffixes

        if name in PROHIBITED_EXACT_PATHS or name.startswith(".coverage."):
            violations.append(f"{normalised}: generated or local-only artifact must not be tracked")
            continue
        if name == "pyvenv.cfg":
            violations.append(f"{normalised}: virtual environment marker must not be tracked")
            continue
        if _has_prohibited_path_part(parts):
            violations.append(f"{normalised}: generated or dependency directory content must not be tracked")
            continue
        if any(suffix in PROHIBITED_SUFFIXES for suffix in suffixes):
            violations.append(f"{normalised}: generated or local-only file type must not be tracked")

    return sorted(violations)


def main() -> int:
    violations = find_repository_hygiene_violations(_tracked_paths())
    if violations:
        print("Repository hygiene gate failed:")
        print("\n".join(violations))
        return 1

    print("Repository hygiene gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
