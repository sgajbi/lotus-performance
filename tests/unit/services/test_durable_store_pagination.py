from app.services.durable_store_pagination import next_offset_or_none


def test_durable_store_pagination_returns_next_offset_when_more_rows_exist():
    assert next_offset_or_none(offset=20, item_count=10, total_count=45) == 30


def test_durable_store_pagination_returns_none_at_or_beyond_total_count():
    assert next_offset_or_none(offset=20, item_count=10, total_count=30) is None
    assert next_offset_or_none(offset=30, item_count=0, total_count=30) is None
