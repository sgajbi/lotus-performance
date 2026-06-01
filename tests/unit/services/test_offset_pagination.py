import pytest
from fastapi import HTTPException

from app.services.offset_pagination import parse_offset_page_token, slice_offset_page


def test_parse_offset_page_token_defaults_missing_token_to_zero():
    assert parse_offset_page_token(None, invalid_detail="invalid", negative_detail="negative") == 0


def test_parse_offset_page_token_rejects_invalid_and_negative_tokens():
    with pytest.raises(HTTPException, match="invalid"):
        parse_offset_page_token("not-a-number", invalid_detail="invalid token", negative_detail="negative token")

    with pytest.raises(HTTPException, match="negative"):
        parse_offset_page_token("-1", invalid_detail="invalid token", negative_detail="negative token")


def test_slice_offset_page_returns_items_and_next_token():
    page = slice_offset_page(
        ["a", "b", "c", "d"],
        page_size=2,
        page_token="1",
        invalid_token_detail="invalid",
        negative_token_detail="negative",
    )

    assert page.items == ["b", "c"]
    assert page.next_page_token == "3"


def test_slice_offset_page_omits_next_token_at_end():
    page = slice_offset_page(
        ["a", "b", "c"],
        page_size=2,
        page_token="1",
        invalid_token_detail="invalid",
        negative_token_detail="negative",
    )

    assert page.items == ["b", "c"]
    assert page.next_page_token is None
