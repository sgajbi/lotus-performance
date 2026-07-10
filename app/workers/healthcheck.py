from __future__ import annotations

import argparse
import sys

from app.services.durability_health_service import check_durable_metadata_store_ready

SUPPORTED_WORKERS = frozenset({"lineage", "compute-executor", "runtime-retention"})


def check_worker_ready(worker_name: str) -> tuple[bool, str]:
    if worker_name not in SUPPORTED_WORKERS:
        return False, f"unsupported_worker:{worker_name}"
    status = check_durable_metadata_store_ready()
    if not status.is_ready:
        return False, status.reason or status.status
    return True, "ready"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker readiness healthcheck for lotus-performance containers.")
    parser.add_argument("worker", choices=sorted(SUPPORTED_WORKERS))
    args = parser.parse_args(argv)

    is_ready, reason = check_worker_ready(args.worker)
    print(f"{args.worker}:{reason}")
    return 0 if is_ready else 1


if __name__ == "__main__":
    sys.exit(main())
