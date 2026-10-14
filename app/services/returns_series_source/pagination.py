"""Token selection shared by source traversal and its lossless archive."""

from collections.abc import Mapping


def next_page_token(payload: Mapping[str, object]) -> str | None:
    token = payload.get("next_page_token")
    if isinstance(token, str) and token.strip():
        return token
    page = payload.get("page")
    if isinstance(page, Mapping):
        token = page.get("next_page_token")
        if isinstance(token, str) and token.strip():
            return token
    return None
