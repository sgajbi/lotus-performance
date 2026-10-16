"""Produce one HIGH/CRITICAL image analysis bound to its actual vulnerability DB.

The acceptance gate remains a separate consumer of the retained report. This
producer records provenance, not vulnerability acceptance or release readiness.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPORT_NAME = "lotus-performance-image-vulnerabilities.json"
DB_METADATA_NAME = "lotus-performance-trivy-db-metadata.json"
PROVENANCE_NAME = "lotus-performance-scan-provenance.json"
SCHEMA = "lotus-performance.container-scan-provenance.v1"
SCANNER_VERSION = "0.71.2"
DOCKER_SOCKET = Path("/var/run/docker.sock")


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _database(cache: Path) -> dict:
    binary = cache / "db" / "trivy.db"
    metadata_path = cache / "db" / "metadata.json"
    if not binary.is_file() or binary.stat().st_size == 0:
        raise ValueError("vulnerability database is missing or empty")
    metadata = json.loads(metadata_path.read_bytes())
    if not isinstance(metadata, dict) or type(metadata.get("Version")) is not int or metadata["Version"] != 2:
        raise ValueError("unsupported vulnerability database schema")
    for field in ("UpdatedAt", "NextUpdate", "DownloadedAt"):
        value = metadata.get(field)
        if not isinstance(value, str) or dt.datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).utcoffset() != dt.timedelta(0):
            raise ValueError("database metadata requires UTC timestamps")
    return {"binary_sha256": _hash(binary), "metadata_sha256": _hash(metadata_path), "metadata": metadata}


def _identity(report_path: Path, source: str, run_id: str) -> dict:
    report = json.loads(report_path.read_bytes())
    if not isinstance(report, dict) or not isinstance(report.get("Results"), list):
        raise ValueError("report requires Results")
    if report.get("Trivy", {}).get("Version") != SCANNER_VERSION:
        raise ValueError("unexpected scanner version")
    metadata = report.get("Metadata", {})
    config = metadata.get("ImageConfig", {})
    labels = config.get("config", {}).get("Labels", {})
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", metadata.get("ImageID", "")):
        raise ValueError("report requires an image identity")
    if config.get("os") != "linux" or config.get("architecture") != "amd64":
        raise ValueError("report platform does not match linux/amd64")
    if labels.get("org.opencontainers.image.revision") != source or labels.get("lotus.ci.pipeline_run_id") != run_id:
        raise ValueError("report source or run identity does not match the build")
    return {
        "image_id": metadata["ImageID"],
        "report_artifact_id": report.get("ArtifactID"),
        "source": source,
        "pipeline_run_id": run_id,
        "platform": "linux/amd64",
        "scanner_version": SCANNER_VERSION,
    }


def _write(path: Path, evidence: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _execute(command: list[str], operations: list[dict], kind: str) -> None:
    result = subprocess.run(command, check=False)
    operations.append({"kind": kind, "argv": command, "native_exit": result.returncode})
    if result.returncode:
        raise ValueError(f"{kind} returned a nonzero native exit")


def _scanner_access() -> tuple[list[str], list[str]]:
    if sys.platform == "win32":
        # Docker Desktop translates Windows bind access; POSIX IDs do not apply.
        return [], []
    if sys.platform != "linux":
        raise ValueError("container evidence supports Linux or Windows Docker hosts")
    uid, gid = os.geteuid(), os.getegid()
    socket = DOCKER_SOCKET.stat()
    if not stat.S_ISSOCK(socket.st_mode):
        raise ValueError("image analysis requires a Unix Docker socket")
    # Write bind-mounted children as the caller that will remove them. The socket
    # can belong to a different group, needed only by the image analysis process.
    return ["--user", f"{uid}:{gid}"], ["--group-add", str(socket.st_gid)]


def _command(
    scanner: str, cache: Path, output: Path, *, analysis: bool, identity: list[str], socket_group: list[str]
) -> list[str]:
    command = ["docker", "run", "--rm", "--platform", "linux/amd64"] + identity + ["-v", f"{cache.as_posix()}:/cache"]
    if analysis:
        command += socket_group + [
            "-v",
            f"{(cache / 'db').as_posix()}:/cache/db:ro",
            "-v",
            f"{output.as_posix()}:/output",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
        ]
    return command + [scanner, "image", "--cache-dir", "/cache"]


def produce(*, image: str, scanner: str, severity: str, output: Path, source: str, run_id: str) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    operations: list[dict] = []
    evidence: dict[str, object] = {
        "schema": SCHEMA,
        "status": "failed",
        "phase": "initializing",
        "operations": operations,
    }
    provenance_path = output / PROVENANCE_NAME
    _write(provenance_path, evidence)
    report_path = output / REPORT_NAME
    metadata_path = output / DB_METADATA_NAME
    # These fixed producer-owned names must not retain a previous successful run.
    report_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    cache: Path | None = None
    failure: Exception | None = None
    try:
        cache = Path(tempfile.mkdtemp(prefix=".trivy-cache-", dir=output))
        if not all((image, scanner, severity, source, run_id)):
            raise ValueError("image, scanner, severity, source and run identity are required")
        scanner_identity, socket_group = _scanner_access()
        evidence["phase"] = "database-acquisition"
        _execute(
            _command(scanner, cache, output, analysis=False, identity=scanner_identity, socket_group=socket_group)
            + ["--download-db-only"],
            operations,
            "db-download-only",
        )
        evidence["phase"] = "database-snapshot"
        before = _database(cache)
        metadata_path.write_bytes((cache / "db" / "metadata.json").read_bytes())
        if _hash(metadata_path) != before["metadata_sha256"]:
            raise ValueError("retained database metadata differs from the snapshot")
        evidence["phase"] = "vulnerability-analysis"
        command = _command(
            scanner, cache, output, analysis=True, identity=scanner_identity, socket_group=socket_group
        ) + [
            "--scanners",
            "vuln",
            "--severity",
            severity,
            "--skip-db-update",
            "--format",
            "json",
            "--output",
            f"/output/{REPORT_NAME}",
            "--exit-code",
            "0",
            image,
        ]
        _execute(command, operations, "vulnerability-analysis")
        evidence["phase"] = "provenance-validation"
        after = _database(cache)
        if before != after:
            raise ValueError("vulnerability database or metadata changed during analysis")
        identity = _identity(report_path, source, run_id)
        evidence.update(
            status="complete",
            phase="complete",
            scanner_image=scanner,
            requested_severity=severity,
            analysis_count=1,
            identity=identity,
            report_sha256=_hash(report_path),
            database_before=before,
            database_after=after,
            database_binary_archived=False,
            acceptance_verdict="not-evaluated",
        )
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        evidence["failure_type"] = type(exc).__name__
        failure = exc
    finally:
        if cache is None:
            evidence["cache_cleanup"] = {"status": "not-created"}
        else:
            try:
                shutil.rmtree(cache)
            except OSError as exc:
                evidence["cache_cleanup"] = {"status": "failed", "failure_type": type(exc).__name__}
                if evidence["status"] == "complete":
                    evidence.update(status="failed", phase="cache-cleanup", failure_type=type(exc).__name__)
                    failure = exc
            else:
                evidence["cache_cleanup"] = {"status": "complete"}
        _write(provenance_path, evidence)
    if failure is not None:
        raise ValueError(f"container evidence failed during {evidence['phase']}") from failure
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--scanner", required=True)
    parser.add_argument("--severity", default="HIGH,CRITICAL")
    parser.add_argument("--output-dir", type=Path, default=Path("output/container-security"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        produce(
            image=args.image,
            scanner=args.scanner,
            severity=args.severity,
            output=args.output_dir,
            source=args.source,
            run_id=args.run_id,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"Container scan evidence produced: one {args.severity} analysis with unchanged actual DB hashes; acceptance pending."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
