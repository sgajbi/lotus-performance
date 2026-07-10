from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

BENCHMARK_PATHS = {
    "full": ("tests/benchmarks",),
    "postgres": (
        "tests/benchmarks/test_postgres_query_plans.py",
        "tests/benchmarks/test_postgres_concurrency_contracts.py",
    ),
}

DEFAULT_POSTGRES_URL = "postgresql+psycopg://lotus:lotus@127.0.0.1:5435/lotus_performance"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run performance characterization with CI artifacts.")
    parser.add_argument("--mode", choices=sorted(BENCHMARK_PATHS), default="full")
    parser.add_argument("--output-dir", default="output/performance-characterization")
    parser.add_argument(
        "--require-non-skipped",
        action="store_true",
        help="Fail when the selected characterization suite only produced skipped tests.",
    )
    parser.add_argument(
        "--postgres-ready-timeout-seconds",
        type=int,
        default=45,
        help="Maximum readiness wait before PostgreSQL characterization fails closed.",
    )
    return parser.parse_args()


def _artifact_stem(mode: str) -> str:
    return "performance-characterization" if mode == "full" else "performance-characterization-postgres"


def _wait_for_postgres(database_url: str, timeout_seconds: int) -> bool:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    deadline = time.monotonic() + timeout_seconds
    while True:
        engine = create_engine(database_url, future=True, connect_args={"connect_timeout": 3})
        try:
            with engine.begin() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except OperationalError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(2)
        finally:
            engine.dispose()


def _read_junit_counts(junit_path: Path) -> dict[str, int]:
    if not junit_path.exists():
        return {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    root = ElementTree.parse(junit_path).getroot()
    if root.tag == "testsuites":
        suites = list(root)
    else:
        suites = [root]

    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.attrib.get(key, "0"))
    return counts


def _write_summary(
    *,
    args: argparse.Namespace,
    command: list[str],
    junit_path: Path,
    log_path: Path,
    return_code: int,
    postgres_ready: bool | None,
) -> Path:
    counts = _read_junit_counts(junit_path)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "command": command,
        "junit_path": junit_path.as_posix(),
        "log_path": log_path.as_posix(),
        "return_code": return_code,
        "tests": counts["tests"],
        "failures": counts["failures"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "postgres_ready": postgres_ready,
        "require_non_skipped": bool(args.require_non_skipped),
    }
    summary_path = Path(args.output_dir) / f"{_artifact_stem(args.mode)}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary_path


def main() -> int:
    args = _parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = _artifact_stem(args.mode)
    junit_path = output_dir / f"{stem}.junit.xml"
    log_path = output_dir / f"{stem}.log"
    postgres_ready: bool | None = None

    if args.mode == "postgres":
        database_url = os.getenv("LOTUS_POSTGRES_PLAN_DATABASE_URL", DEFAULT_POSTGRES_URL)
        postgres_ready = _wait_for_postgres(database_url, args.postgres_ready_timeout_seconds)
        if not postgres_ready:
            log_path.write_text(
                f"PostgreSQL characterization database was unavailable at {database_url}\n",
                encoding="utf-8",
            )
            _write_summary(
                args=args,
                command=[],
                junit_path=junit_path,
                log_path=log_path,
                return_code=2,
                postgres_ready=postgres_ready,
            )
            return 2

    command = [
        sys.executable,
        "-m",
        "pytest",
        *BENCHMARK_PATHS[args.mode],
        "-q",
        "--durations=0",
        f"--junitxml={junit_path}",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    summary_path = _write_summary(
        args=args,
        command=command,
        junit_path=junit_path,
        log_path=log_path,
        return_code=completed.returncode,
        postgres_ready=postgres_ready,
    )

    counts = _read_junit_counts(junit_path)
    if args.require_non_skipped and counts["tests"] > 0 and counts["tests"] == counts["skipped"]:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\nPostgreSQL characterization produced only skipped tests; see {summary_path.as_posix()}.\n")
        return 3

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
