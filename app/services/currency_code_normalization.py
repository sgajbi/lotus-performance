from __future__ import annotations


def normalized_currency_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized_value = value.strip().upper()
    return normalized_value or None
