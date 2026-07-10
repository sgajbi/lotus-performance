from __future__ import annotations

from typing import Any

CALCULATION_ID_PREFIX_MIN_LENGTH = 8
CALCULATION_ID_PREFIX_MAX_LENGTH = 36
CALCULATION_ID_PREFIX_PATTERN = r"^[0-9a-fA-F]{8}[0-9a-fA-F-]{0,28}$"
CALCULATION_ID_PREFIX_DESCRIPTION = (
    "Optional governed calculation-id prefix or full UUID lookup. "
    "Use at least the first eight characters from the start of the calculation UUID; "
    "arbitrary substring search is not supported on operator list paths."
)


def normalize_calculation_id_prefix(value: str | None) -> str | None:
    if value is None:
        return None
    return value.lower()


def apply_calculation_id_prefix_filter(statement: Any, calculation_id_column: Any, value: str | None) -> Any:
    if not value:
        return statement
    return statement.where(calculation_id_column.startswith(value))
