from __future__ import annotations

from collections.abc import Mapping

from app.services.stateful_input_service import RetrievalMetadata


def parse_retrieval_metadata(
    payload: Mapping[str, object],
    *,
    default_chunk_count: int = 1,
    default_page_count: int = 1,
) -> RetrievalMetadata:
    metadata_raw = payload.get("retrieval_metadata")
    if not isinstance(metadata_raw, Mapping):
        return RetrievalMetadata(chunk_count=default_chunk_count, page_count=default_page_count)
    chunk_count = metadata_raw.get("chunk_count")
    page_count = metadata_raw.get("page_count")
    return RetrievalMetadata(
        chunk_count=chunk_count if isinstance(chunk_count, int) and chunk_count > 0 else default_chunk_count,
        page_count=page_count if isinstance(page_count, int) and page_count > 0 else default_page_count,
    )
