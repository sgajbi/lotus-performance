from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.services.runtime_retention_service import run_runtime_retention_cleanup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prune retained lotus-performance runtime state and lineage artifacts.")
    parser.add_argument("--retention-days", type=int, default=None, help="Override runtime retention window in days.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions. Without this flag the command runs in dry-run mode.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_runtime_retention_cleanup(
        retention_days=args.retention_days,
        dry_run=not args.apply,
    )
    print(json.dumps(asdict(summary), indent=2))


if __name__ == "__main__":
    main()
