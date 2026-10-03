"""Capital and P&L ratios: exact monetary division, explicit return domain."""

from decimal import Decimal

import pandas as pd

from engine.numerical_boundary import finite_float64_projection, monetary_arithmetic_context


def add_monetary_series(first: pd.Series, second: pd.Series) -> pd.Series:
    """Build capital without losing small flows beside large admitted balances."""
    left = first.map(_decimal_or_zero)
    right = second.reindex(first.index).map(_decimal_or_zero)
    with monetary_arithmetic_context([*left, *right]):
        return left + right


def calculate_monetary_weights(numerator: pd.Series, denominator: pd.Series, *, decimal_mode: bool) -> pd.Series:
    """Preserve observed money before projecting dimensionless contribution weights."""
    amounts = numerator.map(_decimal_or_zero)
    capitals = denominator.reindex(numerator.index).map(_decimal_or_zero)
    with monetary_arithmetic_context([*amounts, *capitals]):
        weights = pd.Series(
            [_weight(amount, capital) for amount, capital in zip(amounts, capitals, strict=True)],
            index=numerator.index,
            dtype=object,
        )
    return weights if decimal_mode else weights.map(finite_float64_projection)


def _decimal_or_zero(value: object) -> Decimal:
    # Existing panel joins define absent capital as zero weight; public valuation
    # admission independently refuses absent/non-finite required source money.
    return Decimal(0) if pd.isna(value) else Decimal(str(value))


def _weight(amount: Decimal, capital: Decimal) -> Decimal:
    return amount / capital if capital != 0 else Decimal(0)
