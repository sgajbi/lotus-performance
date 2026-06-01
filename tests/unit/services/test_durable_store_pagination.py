from dataclasses import dataclass

from app.services.durable_store_pagination import next_offset_or_none, recovery_cursor_or_none


@dataclass(frozen=True)
class RecoveryItem:
    calculation_id: str
    recovered_at_utc: str


def test_durable_store_pagination_returns_next_offset_when_more_rows_exist():
    assert next_offset_or_none(offset=20, item_count=10, total_count=45) == 30


def test_durable_store_pagination_returns_none_at_or_beyond_total_count():
    assert next_offset_or_none(offset=20, item_count=10, total_count=30) is None
    assert next_offset_or_none(offset=30, item_count=0, total_count=30) is None


def test_recovery_cursor_uses_last_item_when_page_continues():
    cursor = recovery_cursor_or_none(
        next_offset=10,
        items=[
            RecoveryItem(calculation_id="calc-002", recovered_at_utc="2026-05-31T09:00:00Z"),
            RecoveryItem(calculation_id="calc-001", recovered_at_utc="2026-05-31T08:00:00Z"),
        ],
    )

    assert cursor.recovered_before == "2026-05-31T08:00:00Z"
    assert cursor.calculation_id_before == "calc-001"


def test_recovery_cursor_is_empty_for_terminal_or_empty_pages():
    terminal_cursor = recovery_cursor_or_none(
        next_offset=None,
        items=[RecoveryItem(calculation_id="calc-001", recovered_at_utc="2026-05-31T08:00:00Z")],
    )
    empty_cursor = recovery_cursor_or_none(next_offset=10, items=[])

    assert terminal_cursor.recovered_before is None
    assert terminal_cursor.calculation_id_before is None
    assert empty_cursor.recovered_before is None
    assert empty_cursor.calculation_id_before is None
