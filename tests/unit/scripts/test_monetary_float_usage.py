from scripts.check_monetary_float_usage import _finding_key


def test_finding_key_is_stable_when_line_numbers_move():
    original = "app/services/example.py:42:return_value=float(row['return_value'])"
    moved = "app/services/example.py:108:return_value=float(row['return_value'])"

    assert _finding_key(original) == _finding_key(moved)


def test_finding_key_preserves_source_expression():
    approved = "app/services/example.py:42:return_value=float(row['return_value'])"
    changed = "app/services/example.py:42:market_value=float(row['market_value'])"

    assert _finding_key(approved) != _finding_key(changed)
