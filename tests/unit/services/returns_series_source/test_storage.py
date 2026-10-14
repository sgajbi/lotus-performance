import hashlib
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.services.returns_series_source.archive import SourceArchiveError
from app.services.returns_series_source.capture import (
    PortfolioSourceCapture,
    checked_source_file,
    json_bytes,
    source_directory,
    verify_source_bundle,
)
from app.services.returns_series_source.materialization import write_immutable_source_file


@pytest.fixture(autouse=True)
def simulated_directory_durability(monkeypatch):
    # Publication semantics below are fixture controls, not Linux-volume proof.
    monkeypatch.setattr("app.services.returns_series_source.capture.sync_directory", lambda path: None)
    monkeypatch.setattr("app.services.returns_series_source.materialization.sync_directory", lambda path: None)


@pytest.fixture
def captured(tmp_path):
    calculation_id = str(uuid4())
    directory = source_directory(tmp_path, calculation_id)
    capture = PortfolioSourceCapture(
        directory=directory, calculation_id=calculation_id, tenant_id="tenant", attempt_id="attempt"
    )
    capture.plan([("2026-01-01", "2026-01-01")])
    request = {"window": {"start_date": "2026-01-01", "end_date": "2026-01-01"}, "page": {"page_token": None}}
    body = b'{"observations":[],"page":{"returned_row_count":0,"next_page_token":null}}'
    capture.decode(request, httpx.Response(200, content=body))
    root, descriptor = capture.freeze({"original_request": {}, "resolved": {}, "source_inputs": {}})
    return capture, root, descriptor


def test_normalized_decimal_encoding_is_explicit_and_rejects_unsupported_values():
    assert json_bytes({"value": Decimal("1.230000")}) == b'{"value": "1.230000"}'
    for value in (Decimal("NaN"), object()):
        with pytest.raises(TypeError):
            json_bytes({"value": value})


@pytest.mark.parametrize(
    "name", ["../source-x", "source-../escape", "source-\\escape", "source-x:ads", "ordinary.json"]
)
def test_source_paths_refuse_escape_before_file_open(tmp_path, name):
    with pytest.raises(SourceArchiveError):
        checked_source_file(tmp_path, name)
    assert list(tmp_path.iterdir()) == []


def test_source_directory_rejects_noncanonical_identity_before_creating_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        source_directory(tmp_path, str(uuid4()), create=False)
    with pytest.raises(ValueError):
        source_directory(tmp_path, "../escape")
    with pytest.raises(SourceArchiveError):
        source_directory(tmp_path, str(uuid4()).upper())
    assert list(tmp_path.iterdir()) == []


def test_source_paths_refuse_symlink_boundary_before_open(tmp_path, monkeypatch):
    identifier = str(uuid4())
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name in {identifier, "source-file"} or original(path))
    with pytest.raises(SourceArchiveError):
        source_directory(tmp_path, identifier)
    with pytest.raises(SourceArchiveError):
        checked_source_file(tmp_path, "source-file")


@pytest.mark.parametrize("mutation", ["schema", "tenant", "normalized", "path"])
def test_bundle_digest_alone_does_not_bypass_semantic_guards(captured, mutation):
    capture, _, descriptor = captured
    if mutation == "schema":
        descriptor["schema"] = "unsupported"
    elif mutation == "tenant":
        descriptor["scope"]["tenant_id"] = "foreign"
    elif mutation == "normalized":
        descriptor["normalized_sha256"] = "0" * 64
    else:
        descriptor["files"]["archive"] = "../source-escape"
    content = json_bytes(descriptor)
    root = hashlib.sha256(content).hexdigest()
    (capture.directory / f"source-{root}.bundle.json").write_bytes(content)
    with pytest.raises(SourceArchiveError):
        verify_source_bundle(capture.directory, root=root, tenant_id="tenant", calculation_id=capture.calculation_id)


def test_bundle_rejects_invalid_root_and_changed_descriptor(captured):
    capture, root, _ = captured
    with pytest.raises(SourceArchiveError):
        verify_source_bundle(
            capture.directory, root="invalid", tenant_id="tenant", calculation_id=capture.calculation_id
        )
    (capture.directory / f"source-{root}.bundle.json").write_bytes(b"{}")
    with pytest.raises(SourceArchiveError):
        verify_source_bundle(capture.directory, root=root, tenant_id="tenant", calculation_id=capture.calculation_id)


def test_spool_failure_and_missing_planned_chunk_cannot_freeze(captured):
    capture, _, _ = captured
    capture.decode({}, httpx.Response(200, content=b"{}"))
    assert capture.error is not None
    with pytest.raises(SourceArchiveError):
        capture.freeze({})
    capture.error = None
    capture.counts = [0]
    with pytest.raises(SourceArchiveError):
        list(capture.pages())
    capture.plan([("2026-02-01", "2026-02-02")])
    assert capture.error is not None


def test_interrupted_publication_leaves_no_partial_final_and_retry_succeeds(tmp_path, monkeypatch):
    import app.services.returns_series_source.materialization as writer

    with monkeypatch.context() as fault:

        def interrupted(*args):
            raise OSError("interrupted before publication")

        fault.setattr(writer.os, "link", interrupted)
        with pytest.raises(OSError):
            write_immutable_source_file(tmp_path, suffix="response.json", content=b"complete")
    assert list(tmp_path.iterdir()) == []
    name = write_immutable_source_file(tmp_path, suffix="response.json", content=b"complete")
    assert write_immutable_source_file(tmp_path, suffix="response.json", content=b"complete") == name
    (tmp_path / name).write_bytes(b"tampered")
    with pytest.raises(SourceArchiveError):
        write_immutable_source_file(tmp_path, suffix="response.json", content=b"complete")


def test_directory_barrier_failure_retries_existing_publication(tmp_path, monkeypatch):
    from app.services.returns_series_source import capture, materialization

    calls = []
    calculation_id = str(uuid4())

    def fail_parent(path):
        assert path == tmp_path and (tmp_path / calculation_id).is_dir()
        calls.append("parent-failed")
        raise OSError("parent flush failed")

    monkeypatch.setattr(capture, "sync_directory", fail_parent)
    with pytest.raises(OSError, match="parent flush"):
        source_directory(tmp_path, calculation_id)
    monkeypatch.setattr(capture, "sync_directory", lambda path: calls.append("parent-retry"))
    assert source_directory(tmp_path, calculation_id) == tmp_path / calculation_id
    assert calls == ["parent-failed", "parent-retry"]
    calls.clear()

    def fail_after_link(path):
        calls.append(path)
        assert len(list(path.glob("*.response.json"))) == 1
        assert not list(path.glob("source-staging-*"))
        raise OSError("directory flush failed")

    monkeypatch.setattr(materialization, "sync_directory", fail_after_link)
    with pytest.raises(OSError, match="directory flush"):
        write_immutable_source_file(tmp_path, suffix="response.json", content=b"complete")
    published = list(tmp_path.glob("*.response.json"))[0]
    monkeypatch.setattr(materialization, "sync_directory", lambda path: calls.append(path))
    assert write_immutable_source_file(tmp_path, suffix="response.json", content=b"complete") == published.name
    assert calls == [tmp_path, tmp_path] and published.read_bytes() == b"complete"


@pytest.mark.parametrize("failure", [None, "open", "flush"])
def test_linux_directory_barrier_orders_open_flush_close_and_propagates_failure(tmp_path, monkeypatch, failure):
    from app.services.returns_series_source import durability

    events = []
    monkeypatch.setattr(durability.sys, "platform", "linux")
    monkeypatch.setattr(durability.os, "O_DIRECTORY", 0x10000, raising=False)

    def open_directory(path, flags):
        events.append("open")
        assert path == tmp_path and flags == durability.os.O_RDONLY | durability.os.O_DIRECTORY
        if failure == "open":
            raise OSError("open refused")
        return 123

    def flush_directory(descriptor):
        events.append("flush")
        assert descriptor == 123
        if failure == "flush":
            raise OSError("flush refused")

    with monkeypatch.context() as calls:
        calls.setattr(durability.os, "open", open_directory)
        calls.setattr(durability.os, "fsync", flush_directory)
        calls.setattr(durability.os, "close", lambda descriptor: events.append("close"))
        if failure:
            with pytest.raises(OSError, match="refused"):
                durability.sync_directory(tmp_path)
        else:
            durability.sync_directory(tmp_path)
    assert events == (["open"] if failure == "open" else ["open", "flush", "close"])


def test_native_directory_barrier_support_is_explicit(tmp_path):
    import errno
    import sys

    from app.services.returns_series_source.durability import sync_directory

    if sys.platform == "linux":
        sync_directory(tmp_path)
    else:
        with pytest.raises(OSError) as failure:
            sync_directory(tmp_path)
        assert failure.value.errno == errno.ENOTSUP
