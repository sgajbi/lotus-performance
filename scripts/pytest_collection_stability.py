"""Verify that pytest collects the same node-id set under several random seeds."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence


def collect_node_ids(test_path: str, seed: int) -> frozenset[str]:
    """Collect test node ids for one deterministic pytest-randomly seed."""
    command = [
        sys.executable,
        "-m",
        "pytest",
        test_path,
        "--collect-only",
        "-q",
        "--disable-warnings",
        f"--randomly-seed={seed}",
    ]
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"pytest collection failed for seed {seed}: {detail}")

    node_ids = frozenset(line.strip() for line in result.stdout.splitlines() if "::" in line)
    if not node_ids:
        raise RuntimeError(f"pytest collection returned no node ids for seed {seed}")
    return node_ids


def validate_collection_stability(test_path: str, seeds: Sequence[int]) -> int:
    """Return the stable collection size or raise with an actionable set diff."""
    if len(seeds) < 2:
        raise ValueError("at least two seeds are required")

    baseline_seed = seeds[0]
    baseline = collect_node_ids(test_path, baseline_seed)
    for seed in seeds[1:]:
        candidate = collect_node_ids(test_path, seed)
        if candidate != baseline:
            missing = sorted(baseline - candidate)
            unexpected = sorted(candidate - baseline)
            raise RuntimeError(
                f"pytest collection differs between seeds {baseline_seed} and {seed}; "
                f"missing={missing}; unexpected={unexpected}"
            )
    return len(baseline)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_path", nargs="?", default="tests/unit")
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    args = parser.parse_args()

    count = validate_collection_stability(args.test_path, args.seeds)
    print(f"Pytest collection stability passed: tests={count}, seeds={args.seeds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
