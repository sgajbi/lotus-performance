"""Bind PR coverage shards to one revision/run before the existing coverage merge."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from hashlib import sha256
from pathlib import Path

from coverage import CoverageData
from coverage.exceptions import CoverageException

REQUIRED_SHARDS = ("unit", "integration", "e2e", "postgres")


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def identity() -> dict[str, str]:
    values = {key: os.environ.get(key, "") for key in ("CI_EVIDENCE_SHA", "CI_EVIDENCE_RUN")}
    if not all(values.values()):
        raise ValueError("Coverage evidence requires revision and run identity")
    return values


def require_success(results: dict[str, dict[str, str]]) -> None:
    if set(results) != {"test-suites", "postgres-contracts"} or any(
        result.get("result") != "success" for result in results.values()
    ):
        raise ValueError("Both the complete test matrix and PostgreSQL proof must succeed")


def require_data(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty coverage shard: {path.name}")
    data = CoverageData(basename=str(path))
    data.read()
    if not data.measured_files() or not any(data.lines(name) for name in data.measured_files()):
        raise ValueError(f"Coverage shard has no measured lines: {path.name}")


def stamp(shard: str, directory: Path) -> None:
    path = directory / f".coverage.{shard}"
    require_data(path)
    manifest = {**identity(), "shard": shard, "sha256": digest(path)}
    path.with_name(path.name + ".json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")


def verify(directory: Path) -> None:
    expected = identity()
    inputs: list[Path] = []
    wanted = {f".coverage.{shard}" for shard in REQUIRED_SHARDS}
    files = list(directory.rglob(".coverage.*"))
    if {path.name for path in files} != wanted | {name + ".json" for name in wanted}:
        raise ValueError("Coverage inventory must contain exactly all four shards and their manifests")
    if len(files) != len(wanted) * 2:
        raise ValueError("Duplicate coverage shard or manifest")
    for shard in REQUIRED_SHARDS:
        path = next(path for path in files if path.name == f".coverage.{shard}")
        require_data(path)
        manifest = json.loads(path.with_name(path.name + ".json").read_text(encoding="utf-8"))
        if manifest != {**expected, "shard": shard, "sha256": digest(path)}:
            raise ValueError(f"Stale, changed or mismatched coverage evidence: {shard}")
        inputs.append(path)
    # Only validated inputs enter the directory consumed by coverage combine. Never
    # overwrite one shard with another artifact's identically named file.
    for path in inputs:
        shutil.copyfile(path, directory / path.name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stamp", "verify", "results"))
    parser.add_argument("--shard", choices=REQUIRED_SHARDS)
    parser.add_argument("--directory", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        if args.mode == "results":
            require_success(json.loads(os.environ.get("CI_PROOF_RESULTS", "{}")))
        elif args.mode == "stamp":
            if args.shard is None:
                raise ValueError("stamp requires a shard")
            stamp(args.shard, args.directory)
        else:
            verify(args.directory)
    except (ValueError, OSError, CoverageException) as exc:
        print(f"PR coverage evidence refused: {exc}")
        return 1
    print(f"PR coverage evidence {args.mode} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
