"""Materialize fixed source evidence under the existing lineage worker lease."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.durable_store_time import format_timestamp
from app.services.lineage_artifact_classification import lineage_artifact_metadata_by_name
from app.services.lineage_metadata_store import LineageMetadataStore, LineageRecord
from app.services.returns_series_source.archive import SourceArchiveError
from app.services.returns_series_source.capture import (
    checked_source_file,
    file_digest,
    json_bytes,
    source_directory,
    verify_source_bundle,
)
from app.services.returns_series_source.durability import sync_directory


def verify_source_manifest(directory: Path, *, record: LineageRecord) -> dict:
    if record.source_manifest_digest is None or record.source_root_digest is None or record.source_tenant_id is None:
        raise SourceArchiveError("Complete source manifest authority unavailable.")
    path = checked_source_file(directory, f"source-{record.source_manifest_digest}.manifest.json")
    if file_digest(path) != record.source_manifest_digest:
        raise SourceArchiveError("Selected source manifest digest mismatch.")
    manifest = json.loads(path.read_bytes())
    if manifest.get("source_root_digest") != record.source_root_digest:
        raise SourceArchiveError("Selected source manifest root mismatch.")
    if sorted(manifest["artifact_names"]) != sorted(record.artifact_names):
        raise SourceArchiveError("Selected source manifest artifact mismatch.")
    if set(manifest["artifact_sha256"]) != set(record.artifact_names):
        raise SourceArchiveError("Selected source manifest digest inventory mismatch.")
    _verify_manifest_artifacts(directory, record, manifest)
    verify_source_bundle(
        directory,
        root=record.source_root_digest,
        tenant_id=record.source_tenant_id,
        calculation_id=str(record.calculation_id),
    )
    return manifest


def _verify_manifest_artifacts(directory: Path, record: LineageRecord, manifest: dict) -> None:
    for name in record.artifact_names:
        if file_digest(checked_source_file(directory, name)) != manifest["artifact_sha256"][name]:
            raise SourceArchiveError("Retained source artifact digest mismatch.")


def write_immutable_source_file(directory: Path, *, suffix: str, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    name = f"source-{digest}.{suffix}"
    path = checked_source_file(directory, name)
    staging: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix="source-staging-", delete=False) as target:
            staging = Path(target.name)
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        _publish_immutable_source_file(staging, path, digest)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)
    # A matching existing target still needs this barrier: a previous attempt
    # may have linked it and then failed to make the namespace durable.
    sync_directory(directory)
    return name


def _publish_immutable_source_file(staging: Path, target: Path, digest: str) -> None:
    try:
        # Link publication is atomic and refuses an existing name. Unlike an
        # exclusive write to the final path, an interrupted write leaves no
        # partially published immutable file that poisons every retry.
        os.link(staging, target)
    except FileExistsError:
        if file_digest(target) != digest:
            raise SourceArchiveError("Immutable retained source file conflicts.") from None


def materialize_retained_source(
    *,
    record: LineageRecord,
    store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore],
    storage_path: str | Path,
    request_json: str,
    response_json: str,
    worker_id: str | None,
    expected_attempt_count: int | None,
) -> None:
    if record.source_root_digest is None or record.source_tenant_id is None:
        raise SourceArchiveError("Retained source authority unavailable.")
    directory = source_directory(storage_path, str(record.calculation_id))
    descriptor = verify_source_bundle(
        directory,
        root=record.source_root_digest,
        tenant_id=record.source_tenant_id,
        calculation_id=str(record.calculation_id),
    )
    normalized = json.loads(checked_source_file(directory, descriptor["files"]["normalized"]).read_bytes())
    if json.loads(request_json) != normalized["original_request"]:
        raise SourceArchiveError("Materialization request differs from the retained source request.")
    names = [*descriptor["files"].values(), f"source-{record.source_root_digest}.bundle.json"]
    names += [
        write_immutable_source_file(directory, suffix="request.json", content=request_json.encode()),
        write_immutable_source_file(directory, suffix="response.json", content=response_json.encode()),
    ]
    timestamp = datetime.now(timezone.utc)
    manifest = {
        "calculation_type": "ReturnsSeries",
        "timestamp_utc": format_timestamp(timestamp),
        "status": "complete",
        "artifact_names": sorted(names),
        "artifacts": {
            name: value.model_dump(mode="json")
            for name, value in lineage_artifact_metadata_by_name(artifact_names=names).items()
        },
        "source_root_digest": record.source_root_digest,
        "artifact_sha256": {name: file_digest(checked_source_file(directory, name)) for name in names},
        "source_coverage": descriptor["coverage"],
    }
    content = json_bytes(manifest)
    write_immutable_source_file(directory, suffix="manifest.json", content=content)
    store.mark_complete(
        record.calculation_id,
        names,
        timestamp_utc=timestamp,
        worker_id=worker_id,
        source_root_digest=record.source_root_digest,
        source_manifest_digest=hashlib.sha256(content).hexdigest(),
        source_tenant_id=record.source_tenant_id,
        expected_attempt_count=expected_attempt_count,
    )
