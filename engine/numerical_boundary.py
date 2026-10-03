"""Checked interoperability with legacy float64 numerical engines."""

from contextlib import contextmanager
from decimal import Context, Decimal, localcontext
from math import isfinite
from typing import Iterator, Sequence

from engine.exceptions import InvalidEngineInputError


class NumericalDomainError(InvalidEngineInputError, ValueError):
    """Admitted finite financial evidence cannot be projected into the solver domain."""


@contextmanager
def monetary_arithmetic_context(values: Sequence[Decimal], *, products: bool = False) -> Iterator[Context]:
    """Retain sums or pairwise products without unbounded exponent allocation."""
    precision = _required_monetary_precision(values, products=products)
    with localcontext() as context:
        context.prec = max(context.prec, precision)
        yield context


def _required_monetary_precision(values: Sequence[Decimal], *, products: bool) -> int:
    """Validate representation bounds separately from the arithmetic context lifetime."""
    if any(not value.is_finite() for value in values):
        raise NumericalDomainError("Monetary arithmetic requires finite inputs.")
    # Decimal equality drops trailing-zero/exponent distinctions, including an
    # otherwise refused extreme-exponent zero. Deduplicate exact representations,
    # not equivalent amounts; count every observation for carry space.
    distinct_values = [Decimal(text) for text in set(map(str, values))]
    integer_digits = max((max(1, value.adjusted() + 1) for value in distinct_values), default=1)
    fractional_digits = max((max(0, -int(value.as_tuple().exponent)) for value in distinct_values), default=0)
    precision = integer_digits + fractional_digits
    if products:
        # A pairwise product can require both full coefficients, not just the
        # larger input's span. Reserve this before any Decimal multiplication.
        precision = max(precision, _product_coefficient_precision(distinct_values))
    precision += len(str(len(values))) + 16
    if precision > 4096:
        raise NumericalDomainError("Financial inputs exceed the bounded Decimal arithmetic domain.")
    return precision


def _product_coefficient_precision(values: Sequence[Decimal]) -> int:
    return 2 * max((len(value.as_tuple().digits) for value in values), default=1)


def finite_float64_projection(value: Decimal) -> float:
    """Project numerical coefficients only; never replace retained Decimal input evidence."""
    projected = float(value)
    if not isfinite(projected) or (value != 0 and projected == 0):
        raise NumericalDomainError("Financial input is outside the finite float64 numerical domain.")
    return projected
