"""Request-scoped raw page spooling; financial admission and arithmetic stay upstream."""

from __future__ import annotations

import hashlib
import json
import os
from contextvars import ContextVar
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator
from uuid import UUID, uuid4

import httpx

from app.services.http_resilience import response_payload
from app.services.returns_series_source.archive import (
    SourceArchiveDigest,
    SourceArchiveError,
    SourceArchiveScope,
    SourcePage,
    verify_source_archive,
    write_source_archive,
)
from app.services.returns_series_source.durability import sync_directory

active_source_capture: ContextVar[PortfolioSourceCapture | None] = ContextVar("returns_source_capture", default=None)


def _json_default(value: object) -> str:
    if isinstance(value, Decimal) and value.is_finite():
        return str(value)
    raise TypeError("Unsupported normalized source value.")


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False, default=_json_default).encode("utf-8")


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def source_directory(storage_path: str | Path, calculation_id: str, *, create: bool = True) -> Path:
    if str(UUID(calculation_id)) != calculation_id:
        raise SourceArchiveError("Canonical calculation identity required for source storage.")
    base = Path(storage_path).resolve(strict=True)
    directory = base / calculation_id
    if directory.is_symlink():
        raise SourceArchiveError("Source directory cannot be a symbolic link.")
    if create:
        directory.mkdir(exist_ok=True)
    else:
        directory.resolve(strict=True)
    if directory.resolve().parent != base:
        raise SourceArchiveError("Source directory escaped lineage storage.")
    if create:
        # Repeat for existing names too: a previous attempt may have created
        # the directory but failed before its parent publication barrier.
        sync_directory(base)
    return directory


def checked_source_file(directory: Path, name: str) -> Path:
    # All retained source names are generated here; no archive extraction or
    # caller-supplied relative paths are supported.
    if Path(name).name != name or not name.startswith("source-") or ":" in name or "\\" in name:
        raise SourceArchiveError("Invalid retained source filename.")
    path = directory / name
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        raise SourceArchiveError("Source file escaped lineage storage.")
    return path


def _flush(file: Any) -> None:
    file.flush()
    os.fsync(file.fileno())


class PortfolioSourceCapture:
    """Spool each successful response once, preserving opaque tokens and bytes.

    The planned windows come from the actual source resolver, not observed
    responses. Chunk bodies are kept on disk; memory holds one page and the
    existing chunk plan. A failed spool is explicit and never aborts arithmetic.
    """

    def __init__(self, *, directory: Path, calculation_id: str, tenant_id: str, attempt_id: str):
        self.directory = directory
        self.calculation_id = calculation_id
        self.tenant_id = tenant_id
        self.attempt_id = attempt_id
        self.spool = directory / f"source-spool-{uuid4().hex}"
        self.spool.mkdir()
        self.windows: list[tuple[str, str]] = []
        self.counts: list[int] = []
        self.error: str | None = None
        self.normalized_sources: dict[str, Any] = {}

    def plan(self, windows: Iterable[tuple[str, str]]) -> None:
        if self.windows:
            self.error = "Multiple portfolio retrieval plans in one source capture."
            return
        self.windows = list(windows)
        self.counts = [0] * len(self.windows)

    def decode(self, request: dict[str, Any], response: httpx.Response) -> dict[str, Any]:
        if 200 <= response.status_code < 300 and self.error is None:
            try:
                window = request["window"]
                chunk = self.windows.index((window["start_date"], window["end_date"]))
                number = self.counts[chunk]
                with (self.spool / f"{chunk}-{number}.body").open("xb") as body:
                    body.write(response.content)
                    _flush(body)
                with (self.spool / f"{chunk}-{number}.request").open("xb") as target:
                    target.write(json_bytes(request))
                    _flush(target)
                self.counts[chunk] += 1
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.error = f"Source spool failed: {type(exc).__name__}"
        return response_payload(response)

    def pages(self) -> Iterator[SourcePage]:
        for chunk, count in enumerate(self.counts):
            if count == 0:
                raise SourceArchiveError("A planned source chunk has no captured pages.")
            for number in range(count):
                yield SourcePage(
                    chunk,
                    number,
                    json.loads((self.spool / f"{chunk}-{number}.request").read_bytes()),
                    (self.spool / f"{chunk}-{number}.body").read_bytes(),
                )

    def freeze(self, normalized: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if self.error or not self.windows:
            raise SourceArchiveError(self.error or "Source capture has no retrieval plan.")
        scope = SourceArchiveScope(self.calculation_id, self.tenant_id, self.attempt_id, len(self.windows))
        prefix = f"source-{hashlib.sha256(json_bytes(asdict(scope))).hexdigest()}"
        names = {"archive": f"{prefix}.bin", "index": f"{prefix}.jsonl", "normalized": f"{prefix}.json"}
        with checked_source_file(self.directory, names["archive"]).open("xb") as body:
            with checked_source_file(self.directory, names["index"]).open("xb") as index:
                digest = write_source_archive(self.pages(), scope=scope, archive=body, index=index)
                _flush(body)
                _flush(index)
        normalized_path = checked_source_file(self.directory, names["normalized"])
        with normalized_path.open("x", encoding="utf-8", newline="\n") as target:
            # iterencode avoids an additional full normalized-payload string.
            for piece in json.JSONEncoder(sort_keys=True, allow_nan=False, default=_json_default).iterencode(
                normalized
            ):
                target.write(piece)
            _flush(target)
        descriptor = {
            "schema": "lotus-performance.returns-source-bundle.v1",
            "scope": asdict(scope),
            "archive_digest": asdict(digest),
            "files": names,
            "normalized_sha256": file_digest(normalized_path),
            "coverage": {"portfolio_timeseries": "complete", "benchmark": "unavailable", "risk_free": "unavailable"},
        }
        root = hashlib.sha256(json_bytes(descriptor)).hexdigest()
        with checked_source_file(self.directory, f"source-{root}.bundle.json").open("xb") as target:
            target.write(json_bytes(descriptor))
            _flush(target)
        verify_source_bundle(self.directory, root=root, tenant_id=self.tenant_id, calculation_id=self.calculation_id)
        sync_directory(self.directory)
        return root, descriptor


def verify_source_bundle(directory: Path, *, root: str, tenant_id: str, calculation_id: str) -> dict[str, Any]:
    """The root must come from durable tenant authority, never an input archive."""
    import re

    if re.fullmatch(r"[0-9a-f]{64}", root) is None:
        raise SourceArchiveError("Invalid source root.")
    descriptor_bytes = checked_source_file(directory, f"source-{root}.bundle.json").read_bytes()
    if hashlib.sha256(descriptor_bytes).hexdigest() != root:
        raise SourceArchiveError("Source bundle digest mismatch.")
    descriptor = json.loads(descriptor_bytes)
    if descriptor.get("schema") != "lotus-performance.returns-source-bundle.v1":
        raise SourceArchiveError("Unsupported source bundle schema.")
    scope = SourceArchiveScope(**descriptor["scope"])
    scope.validate()
    if scope.tenant_id != tenant_id or scope.calculation_id != calculation_id:
        raise SourceArchiveError("Source bundle authority mismatch.")
    names = descriptor["files"]
    with checked_source_file(directory, names["archive"]).open("rb") as body:
        with checked_source_file(directory, names["index"]).open("rb") as index:
            verify_source_archive(
                body, index, scope=scope, expected=SourceArchiveDigest(**descriptor["archive_digest"])
            )
    if file_digest(checked_source_file(directory, names["normalized"])) != descriptor["normalized_sha256"]:
        raise SourceArchiveError("Normalized source digest mismatch.")
    return descriptor
