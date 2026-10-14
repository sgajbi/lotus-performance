"""Lossless archive controls; no producer, queue or public custody claim."""

import hashlib
import io
import json
from dataclasses import replace

import pytest

from app.services.returns_series_source.archive import (
    SourceArchiveError,
    SourceArchiveScope,
    SourcePage,
    verify_source_archive,
    write_source_archive,
)


def scope():
    return SourceArchiveScope("b981bcc7-892e-412d-8e24-abbef356e641", "tenant-a", "attempt-a", 1)


def page(*, chunk=0, number=0, token=None, next_token=None):
    body = (
        (
            '{"observations":[{"valuation_date":"2026-03-12",'
            '"beginning_market_value":"12345678901234567890.12345678901234567890",'
            '"ending_market_value":"12345678901234567889.12345678901234567890",'
            '"cash_flows":[{"amount":"-1.00000000000000000000","timing":"eod",'
            '"cash_flow_type":"fee","flow_scope":"operational","source_classification":"EXPENSE"}]}],'
            '"page":{"returned_row_count":1,"next_page_token":NEXT}}'
        )
        .replace("NEXT", json.dumps(next_token))
        .encode()
    )
    return SourcePage(chunk, number, {"page": {"page_token": token}}, body)


def archive(pages=None, *, capture_scope=None):
    body, index = io.BytesIO(), io.BytesIO()
    expected = write_source_archive(pages or [page()], scope=capture_scope or scope(), archive=body, index=index)
    body.seek(0)
    index.seek(0)
    return body, index, expected


def test_roundtrip_preserves_exact_source_bytes_and_existing_parsed_fingerprint():
    original = page()
    body, index, expected = archive([original])
    assert body.getvalue() == original.response_body
    records = [json.loads(line) for line in index.getvalue().splitlines()]
    assert (
        records[1]["response_fingerprint"]
        == hashlib.sha256(json.dumps(json.loads(original.response_body), sort_keys=True).encode()).hexdigest()
    )
    assert verify_source_archive(body, index, scope=scope(), expected=expected) == expected
    assert expected.page_count == 1
    assert expected.observation_count == 1


@pytest.mark.parametrize("metadata", [{}, {"page": {}}, {"next_page_token": None}, {"page": {"next_page_token": None}}])
def test_optional_page_metadata_preserves_raw_bytes(metadata):
    payload = {"observations": [{"amount": "123456789.123456789"}], **metadata}
    raw = json.dumps(payload, indent=2).encode()
    body, index, expected = archive([replace(page(), response_body=raw)])
    assert body.getvalue() == raw and expected.observation_count == 1
    assert verify_source_archive(body, index, scope=scope(), expected=expected) == expected


def test_archive_selects_top_level_token_before_nested_token():
    first = json.loads(page().response_body)
    first["next_page_token"] = "top"
    first["page"]["next_page_token"] = "nested"
    body, index, expected = archive(
        [replace(page(), response_body=json.dumps(first).encode()), page(number=1, token="top")]
    )
    assert expected.page_count == 2
    assert verify_source_archive(body, index, scope=scope(), expected=expected) == expected


@pytest.mark.parametrize("blank", ["", " \t"])
def test_blank_response_tokens_use_nested_continuation_and_preserve_exact_bytes(blank):
    first = json.loads(page(next_token="nested").response_body)
    first["next_page_token"] = blank
    terminal = json.loads(page().response_body)
    terminal["next_page_token"] = blank
    terminal["page"]["next_page_token"] = blank
    pages = [
        replace(page(), response_body=json.dumps(first, indent=2).encode()),
        replace(page(number=1, token="nested"), response_body=json.dumps(terminal, indent=2).encode()),
    ]
    body, index, expected = archive(pages)
    assert body.getvalue() == b"".join(source.response_body for source in pages)
    assert expected.page_count == 2 and expected.observation_count == 2
    assert verify_source_archive(body, index, scope=scope(), expected=expected) == expected


@pytest.mark.parametrize(
    "metadata",
    [
        {"page": None},
        {"page": []},
        {"page": {"returned_row_count": None}},
        {"page": {"returned_row_count": True}},
        {"page": {"returned_row_count": -1}},
        {"page": {"returned_row_count": 2}},
        {"next_page_token": 3},
        {"page": {"next_page_token": []}},
        {"next_page_token": "", "page": {"next_page_token": False}},
        {"next_page_token": "valid", "page": {"next_page_token": {}}},
        {"next_page_token": " padded "},
    ],
)
def test_supplied_malformed_pagination_still_refuses(metadata):
    with pytest.raises(SourceArchiveError):
        archive([replace(page(), response_body=json.dumps({"observations": [{}], **metadata}).encode())])


def test_complete_multi_chunk_traversal_and_duplicate_source_rows_preserved():
    pages = [page(next_token="opaque"), page(number=1, token="opaque"), page(chunk=1)]
    capture_scope = replace(scope(), chunk_count=2)
    body, index, expected = archive(pages, capture_scope=capture_scope)
    assert verify_source_archive(body, index, scope=capture_scope, expected=expected).page_count == 3
    assert body.getvalue() == b"".join(p.response_body for p in pages)


@pytest.mark.parametrize(
    "pages,capture_scope",
    [
        ([page(next_token="unresolved")], scope()),
        ([page(next_token="a"), page(number=1, token="b")], scope()),
        ([page(number=1)], scope()),
        ([page(chunk=1)], scope()),
        ([page(), page()], scope()),
        ([page()], replace(scope(), chunk_count=2)),
        ([page(), page(chunk=1)], scope()),
        ([page(next_token="a"), page(number=1, token="a", next_token="a"), page(number=2, token="a")], scope()),
    ],
)
def test_incomplete_or_reordered_traversal_refuses_complete_digest(pages, capture_scope):
    with pytest.raises(SourceArchiveError):
        archive(pages, capture_scope=capture_scope)


@pytest.mark.parametrize("body", [b"{", b'{"observations":[],"page":{"returned_row_count":1}}', b'{"x":NaN}'])
def test_malformed_source_refuses(body):
    with pytest.raises(SourceArchiveError):
        archive([replace(page(), response_body=body)])


def test_same_size_tamper_and_truncated_or_extra_body_refuse():
    body, index, expected = archive()
    for bad in [body.getvalue().replace(b"-1.0", b"-2.0"), body.getvalue()[:-1], body.getvalue() + b" "]:
        with pytest.raises(SourceArchiveError):
            verify_source_archive(io.BytesIO(bad), io.BytesIO(index.getvalue()), scope=scope(), expected=expected)


def test_index_tamper_missing_and_reordered_pages_refuse():
    body, index, expected = archive([page(next_token="a"), page(number=1, token="a")])
    lines = index.getvalue().splitlines(keepends=True)
    for bad in [
        b"".join(lines[:2]),
        lines[0] + lines[2] + lines[1],
        index.getvalue().replace(b"tenant-a", b"tenant-b"),
    ]:
        with pytest.raises(SourceArchiveError):
            verify_source_archive(io.BytesIO(body.getvalue()), io.BytesIO(bad), scope=scope(), expected=expected)


def test_wrong_scope_and_missing_authority_refuse():
    body, index, expected = archive()
    with pytest.raises(SourceArchiveError):
        verify_source_archive(body, index, scope=replace(scope(), tenant_id="tenant-b"), expected=expected)
    for tenant in ["", " "]:
        with pytest.raises(SourceArchiveError):
            archive(capture_scope=replace(scope(), tenant_id=tenant))


def test_storage_failure_propagates_without_success_digest():
    class FailedWriter(io.BytesIO):
        def write(self, data):
            raise OSError("owned fixture storage unavailable")

    with pytest.raises(OSError, match="unavailable"):
        write_source_archive([page()], scope=scope(), archive=FailedWriter(), index=io.BytesIO())


def test_writer_consumes_generator_once_and_verifier_never_requests_unbounded_archive_read():
    class BoundedReader(io.BytesIO):
        def read(self, size=-1):
            assert size >= 0
            return super().read(size)

    body, index, expected = archive(iter([page()]))
    assert verify_source_archive(BoundedReader(body.getvalue()), index, scope=scope(), expected=expected) == expected


@pytest.mark.parametrize(
    "capture_scope",
    [
        replace(scope(), calculation_id="not-a-uuid"),
        replace(scope(), calculation_id=scope().calculation_id.upper()),
        replace(scope(), chunk_count=0),
        replace(scope(), chunk_count=True),
    ],
)
def test_invalid_capture_identity_refuses(capture_scope):
    with pytest.raises(SourceArchiveError):
        archive(capture_scope=capture_scope)


@pytest.mark.parametrize(
    "source",
    [
        replace(page(), response_body=b"[]"),
        replace(page(), response_body=b"{}"),
        replace(page(), response_body=b'{"a":1,"a":2}'),
        replace(page(), request_payload={"page": {"page_token": ""}}),
        replace(page(), request_payload={"page": {"page_token": " \t"}}),
        replace(page(), request_payload={"page": {"page_token": False}}),
        replace(page(), number=True),
        replace(
            page(),
            response_body=page().response_body.replace(b'"observations":', b'"unsupported":1e999,"observations":'),
        ),
    ],
)
def test_invalid_source_representation_refuses(source):
    with pytest.raises(SourceArchiveError):
        archive([source])


@pytest.mark.parametrize("change", ["missing_length", "negative_length", "changed_page_hash"])
def test_untrusted_index_controls(change):
    body, index, expected = archive()
    records = [json.loads(line) for line in index.getvalue().splitlines()]
    if change == "missing_length":
        del records[1]["bytes"]
    elif change == "negative_length":
        records[1]["bytes"] = -1
    else:
        records[1]["sha256"] = "0" * 64
    bad = b"".join(json.dumps(record).encode() + b"\n" for record in records)
    with pytest.raises(SourceArchiveError):
        verify_source_archive(body, io.BytesIO(bad), scope=scope(), expected=expected)


def test_external_digest_authority_is_required():
    body, index, expected = archive()
    changed = replace(expected, observation_count=2)
    assert expected.root_sha256 != changed.root_sha256
    with pytest.raises(SourceArchiveError, match="trusted digest"):
        verify_source_archive(body, index, scope=scope(), expected=changed)


def test_short_storage_write_refuses():
    class ShortWriter(io.BytesIO):
        def write(self, data):
            return len(data) - 1

    with pytest.raises(OSError, match="Incomplete"):
        write_source_archive([page()], scope=scope(), archive=io.BytesIO(), index=ShortWriter())
