from app.services.stateful_input_service import RetrievalMetadata
from app.services.stateful_retrieval_metadata import (
    add_zero_default_retrieval_metadata,
    parse_retrieval_metadata,
    parse_zero_default_retrieval_metadata,
)


def test_parse_retrieval_metadata_defaults_missing_payload_to_one_chunk_and_page():
    assert parse_retrieval_metadata({}) == RetrievalMetadata(chunk_count=1, page_count=1)


def test_parse_retrieval_metadata_preserves_positive_integer_counts():
    assert parse_retrieval_metadata({"retrieval_metadata": {"chunk_count": 2, "page_count": 3}}) == RetrievalMetadata(
        chunk_count=2, page_count=3
    )


def test_parse_retrieval_metadata_uses_configured_defaults_for_invalid_counts():
    assert parse_retrieval_metadata(
        {"retrieval_metadata": {"chunk_count": 0, "page_count": "3"}},
        default_chunk_count=0,
        default_page_count=0,
    ) == RetrievalMetadata(chunk_count=0, page_count=0)


def test_parse_retrieval_metadata_defaults_boolean_counts():
    assert parse_retrieval_metadata(
        {"retrieval_metadata": {"chunk_count": True, "page_count": True}},
        default_chunk_count=0,
        default_page_count=0,
    ) == RetrievalMetadata(chunk_count=0, page_count=0)
    assert parse_zero_default_retrieval_metadata(
        {"retrieval_metadata": {"chunk_count": True, "page_count": True}}
    ) == RetrievalMetadata(chunk_count=0, page_count=0)


def test_parse_retrieval_metadata_can_preserve_legacy_numeric_coercion():
    assert parse_retrieval_metadata(
        {"retrieval_metadata": {"chunk_count": "2", "page_count": 3.0}},
        default_chunk_count=0,
        default_page_count=0,
        coerce_numeric_counts=True,
    ) == RetrievalMetadata(chunk_count=2, page_count=3)


def test_parse_zero_default_retrieval_metadata_defaults_missing_payload_to_zero():
    assert parse_zero_default_retrieval_metadata(None) == RetrievalMetadata(chunk_count=0, page_count=0)
    assert parse_zero_default_retrieval_metadata({}) == RetrievalMetadata(chunk_count=0, page_count=0)
    assert parse_zero_default_retrieval_metadata(
        {"retrieval_metadata": {"chunk_count": "2", "page_count": 3.0}}
    ) == RetrievalMetadata(chunk_count=2, page_count=3)


def test_add_zero_default_retrieval_metadata_accumulates_payload_counts():
    assert add_zero_default_retrieval_metadata(
        RetrievalMetadata(chunk_count=1, page_count=2),
        {"retrieval_metadata": {"chunk_count": "3", "page_count": 4.0}},
    ) == RetrievalMetadata(chunk_count=4, page_count=6)
