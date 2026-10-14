"""Streaming portfolio source archive codec; the execution store owns custody.

The caller owns storage, publication, leases and tenant authorization. Verification
requires digests obtained from that authority, not from the untrusted archive.
Bodies are concatenated unchanged; a JSON-lines index gives ordered byte ranges.
Page bytes are processed one page at a time. Token-loop detection retains the
opaque token set for the current chunk; the archive body is never fully loaded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, BinaryIO
from uuid import UUID

from app.services.returns_series_source.pagination import next_page_token

_SCHEMA = "lotus-performance.portfolio-source-archive.v1"
_BUFFER_SIZE = 64 * 1024  # IO buffer, not a financial admission limit.


class SourceArchiveError(ValueError):
    """The supplied source archive cannot establish complete byte custody."""


@dataclass(frozen=True)
class SourceArchiveScope:
    calculation_id: str
    tenant_id: str
    attempt_id: str
    chunk_count: int

    def validate(self) -> None:
        _validate_calculation_identity(self.calculation_id)
        if any(not _explicit_identity(v) for v in (self.tenant_id, self.attempt_id)):
            raise SourceArchiveError("Explicit tenant and attempt identity required.")
        if type(self.chunk_count) is not int or self.chunk_count < 1:
            raise SourceArchiveError("Positive expected chunk count required.")


def _explicit_identity(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _validate_calculation_identity(value: str) -> None:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise SourceArchiveError("Canonical calculation identity required.") from exc


@dataclass(frozen=True)
class SourcePage:
    chunk: int
    number: int
    request_payload: dict[str, Any]
    response_body: bytes


@dataclass(frozen=True)
class SourceArchiveDigest:
    archive_sha256: str
    index_sha256: str
    page_count: int
    observation_count: int
    byte_count: int

    @property
    def root_sha256(self) -> str:
        return hashlib.sha256(_encode(asdict(self))).hexdigest()


def _encode(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise SourceArchiveError("Unsupported JSON representation.") from exc


def _reject_constant(value: str) -> None:
    raise SourceArchiveError("Nonfinite JSON value.")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceArchiveError("Duplicate JSON member.")
        result[key] = value
    return result


def _decode(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise SourceArchiveError("Invalid source JSON object.") from exc
    if not isinstance(value, dict):
        raise SourceArchiveError("Source JSON object required.")
    return value


def _token(value: object) -> str | None:
    if value is None or isinstance(value, str) and value:
        return value
    raise SourceArchiveError("Opaque page token must be null or nonempty string.")


def _validate_response_token(value: object) -> None:
    """Blank response strings are absent to the shared selector; request tokens stay strict."""
    if value is not None and not isinstance(value, str):
        raise SourceArchiveError("Response page token must be null or string.")


@dataclass
class _Traversal:
    scope: SourceArchiveScope
    chunk: int = -1
    number: int = -1
    next_token: str | None = None
    page_count: int = 0
    observation_count: int = 0
    byte_count: int = 0
    seen_tokens: set[str] = field(default_factory=set)

    def accept(self, source: SourcePage) -> dict[str, Any]:
        self._check_sequence(source)
        payload, requested_token, returned_token, count = _source_page_details(source)
        self._check_tokens(requested_token, returned_token)
        record = {
            "chunk": source.chunk,
            "page": source.number,
            "offset": self.byte_count,
            "bytes": len(source.response_body),
            "sha256": hashlib.sha256(source.response_body).hexdigest(),
            "request": source.request_payload,
            "request_fingerprint": hashlib.sha256(_encode(source.request_payload)).hexdigest(),
            "response_fingerprint": hashlib.sha256(_encode(payload)).hexdigest(),
            "observations": count,
        }
        self.chunk, self.number, self.next_token = source.chunk, source.number, returned_token
        self.page_count += 1
        self.observation_count += count
        self.byte_count += len(source.response_body)
        return record

    def _check_sequence(self, source: SourcePage) -> None:
        if type(source.chunk) is not int or type(source.number) is not int:
            raise SourceArchiveError("Integer chunk/page sequence required.")
        expected = (self.chunk, self.number + 1) if self.next_token is not None else (self.chunk + 1, 0)
        if (source.chunk, source.number) != expected:
            raise SourceArchiveError("Page or chunk order or incomplete previous chunk.")
        if source.chunk >= self.scope.chunk_count:
            raise SourceArchiveError("Unexpected source chunk.")
        if source.chunk != self.chunk:
            self.seen_tokens.clear()

    def _check_tokens(self, requested_token: str | None, returned_token: str | None) -> None:
        if requested_token != self.next_token:
            raise SourceArchiveError("Source traversal token mismatch.")
        if returned_token is not None:
            if returned_token in self.seen_tokens:
                raise SourceArchiveError("Repeated source traversal token.")
            self.seen_tokens.add(returned_token)

    def finish(self) -> None:
        if self.chunk != self.scope.chunk_count - 1 or self.next_token is not None:
            raise SourceArchiveError("Source traversal incomplete.")


def _source_page_details(source: SourcePage) -> tuple[dict[str, Any], str | None, str | None, int]:
    try:
        requested_token = _token(source.request_payload["page"]["page_token"])
        payload = _decode(source.response_body)
        observations = payload["observations"]
        page_metadata = payload.get("page", {})
        if not isinstance(page_metadata, dict):
            raise SourceArchiveError("Malformed source page metadata.")
        for metadata in (payload, page_metadata):
            _validate_response_token(metadata.get("next_page_token"))
        returned_token = _token(next_page_token(payload))
        count = page_metadata.get("returned_row_count", len(observations))
    except (KeyError, TypeError) as exc:
        raise SourceArchiveError("Required source page fields missing.") from exc
    if type(count) is not int or not isinstance(observations, list) or count != len(observations):
        raise SourceArchiveError("Source observation count mismatch.")
    return payload, requested_token, returned_token, count


def _write(stream: BinaryIO, data: bytes) -> None:
    if stream.write(data) != len(data):
        raise OSError("Incomplete source artifact write.")


def _header(scope: SourceArchiveScope) -> dict[str, Any]:
    scope.validate()
    return {"schema": _SCHEMA, "scope": asdict(scope), "source_family": "portfolio_timeseries"}


def write_source_archive(
    pages: Iterable[SourcePage], *, scope: SourceArchiveScope, archive: BinaryIO, index: BinaryIO
) -> SourceArchiveDigest:
    """Write caller-owned staging streams; failure never returns a complete digest.

    This function neither publishes files nor overwrites a retained bundle. The
    caller must discard/unpublish partial staging output on any exception.
    """
    header = _encode(_header(scope)) + b"\n"
    _write(index, header)
    index_hash, archive_hash = hashlib.sha256(header), hashlib.sha256()
    traversal = _Traversal(scope)
    for page in pages:
        record = traversal.accept(page)
        _write(archive, page.response_body)
        archive_hash.update(page.response_body)
        line = _encode(record) + b"\n"
        _write(index, line)
        index_hash.update(line)
    traversal.finish()
    return SourceArchiveDigest(
        archive_hash.hexdigest(),
        index_hash.hexdigest(),
        traversal.page_count,
        traversal.observation_count,
        traversal.byte_count,
    )


def _read_page(archive: BinaryIO, size: object) -> bytes:
    if type(size) is not int or size < 1:
        raise SourceArchiveError("Positive page byte length required.")
    parts = []
    remaining = size
    while remaining:
        part = archive.read(min(remaining, _BUFFER_SIZE))
        if not part:
            raise SourceArchiveError("Truncated source archive.")
        parts.append(part)
        remaining -= len(part)
    return b"".join(parts)


def verify_source_archive(
    archive: BinaryIO, index: BinaryIO, *, scope: SourceArchiveScope, expected: SourceArchiveDigest
) -> SourceArchiveDigest:
    """Verify all bytes/traversal against externally trusted scope and digests.

    No content is returned for execution before the entire chain verifies. The
    caller still owns tenant authorization, lease/CAS, immutable reads and replay.
    """
    header = index.readline()
    if _decode(header) != _header(scope):
        raise SourceArchiveError("Source archive scope/schema mismatch.")
    index_hash, archive_hash = hashlib.sha256(header), hashlib.sha256()
    traversal = _Traversal(scope)
    for line in index:
        record = _decode(line)
        try:
            body = _read_page(archive, record["bytes"])
            actual = traversal.accept(SourcePage(record["chunk"], record["page"], record["request"], body))
        except KeyError as exc:
            raise SourceArchiveError("Incomplete source page index.") from exc
        if actual != record:
            raise SourceArchiveError("Source page index/content mismatch.")
        archive_hash.update(body)
        index_hash.update(line)
    if archive.read(1):
        raise SourceArchiveError("Undeclared source bytes.")
    traversal.finish()
    actual_digest = SourceArchiveDigest(
        archive_hash.hexdigest(),
        index_hash.hexdigest(),
        traversal.page_count,
        traversal.observation_count,
        traversal.byte_count,
    )
    if actual_digest != expected:
        raise SourceArchiveError("Source archive trusted digest mismatch.")
    return actual_digest
