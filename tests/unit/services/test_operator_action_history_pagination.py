from app.services.operator_action_history_pagination import paginate_history_entries


def test_operator_action_history_pagination_returns_full_tail_without_limit():
    page = paginate_history_entries(["a", "b", "c"], limit=None, offset=1)

    assert page.entries == ["b", "c"]
    assert page.next_offset is None


def test_operator_action_history_pagination_returns_next_offset_when_more_entries_remain():
    page = paginate_history_entries(["a", "b", "c"], limit=1, offset=1)

    assert page.entries == ["b"]
    assert page.next_offset == 2


def test_operator_action_history_pagination_omits_next_offset_at_end():
    page = paginate_history_entries(["a", "b", "c"], limit=2, offset=1)

    assert page.entries == ["b", "c"]
    assert page.next_offset is None
