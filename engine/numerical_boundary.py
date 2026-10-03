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
    if any(not value.is_finite() for value in values):
        raise NumericalDomainError("Monetary arithmetic requires finite inputs.")
    integer_digits = max((max(1, value.adjusted() + 1) for value in values), default=1)
    fractional_digits = max((max(0, -int(value.as_tuple().exponent)) for value in values), default=0)
    precision = integer_digits + fractional_digits
    if products:
        # A pairwise product can require both full coefficients, not just the
        # larger input's span. Reserve this before any Decimal multiplication.
        coefficient_digits = max((len(value.as_tuple().digits) for value in values), default=1)
        precision = max(precision, 2 * coefficient_digits)
    precision += len(str(len(values))) + 16
    if precision > 4096:
        raise NumericalDomainError("Financial inputs exceed the bounded Decimal arithmetic domain.")
    with localcontext() as context:
        context.prec = max(context.prec, precision)
        yield context


def finite_float64_projection(value: Decimal) -> float:
    """Project numerical coefficients only; never replace retained Decimal input evidence."""
    projected = float(value)
    if not isfinite(projected) or (value != 0 and projected == 0):
        raise NumericalDomainError("Financial input is outside the finite float64 numerical domain.")
    return projected
