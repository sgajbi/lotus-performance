"""Annual cross-sectional statistics over already qualified full-year members."""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext
from typing import Literal, Sequence

from engine.composites import COMPOSITE_RETURN_QUANTUM, _quantize_decimal, _sample_standard_deviation

AnnualDispersionMethod = Literal["EQUAL_WEIGHT_SAMPLE_STDDEV", "YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV"]


class AnnualDispersionDomainError(ValueError):
    pass


@dataclass(frozen=True)
class AnnualMemberReturn:
    portfolio_id: str
    annual_return: Decimal
    year_begin_assets: Decimal


def _finite(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise AnnualDispersionDomainError("Finite Decimal evidence is required")
    if value and abs(value.adjusted()) > 128:
        raise AnnualDispersionDomainError("Decimal magnitude exceeds the registered annual method domain")


def link_full_year_member_return(monthly_returns: Sequence[Decimal]) -> Decimal:
    if len(monthly_returns) != 12:
        raise AnnualDispersionDomainError("Twelve complete monthly returns are required")
    try:
        with localcontext() as context:
            context.prec = 60
            context.rounding = ROUND_HALF_EVEN
            context.Emax = 128
            context.Emin = -128
            growth = Decimal(1)
            for value in monthly_returns:
                _finite(value)
                if value < -1:
                    raise AnnualDispersionDomainError("Negative growth factors are unsupported")
                growth *= 1 + value
            return growth - 1
    except DecimalException as exc:
        raise AnnualDispersionDomainError("Annual linking exceeds the Decimal domain") from exc


def _qualified_members(members: Sequence[AnnualMemberReturn]) -> list[AnnualMemberReturn]:
    if len(members) > 1000 or len({item.portfolio_id for item in members}) != len(members):
        raise AnnualDispersionDomainError("Annual members must be unique and bounded to 1000")
    ordered = sorted(members, key=lambda item: item.portfolio_id)
    for item in ordered:
        _finite(item.annual_return)
        if item.annual_return < -1:
            raise AnnualDispersionDomainError("Negative annual growth factors are unsupported")
    return ordered


def _asset_weighted_population_dispersion(ordered: Sequence[AnnualMemberReturn]) -> Decimal | None:
    for item in ordered:
        _finite(item.year_begin_assets)
        if item.year_begin_assets <= 0:
            raise AnnualDispersionDomainError("Year-begin assets must be positive")
    if len(ordered) < 2:
        return None
    total = sum((item.year_begin_assets for item in ordered), Decimal(0))
    mean = sum((item.year_begin_assets * item.annual_return for item in ordered), Decimal(0)) / total
    variance = sum((item.year_begin_assets * (item.annual_return - mean) ** 2 for item in ordered), Decimal(0)) / total
    return _quantize_decimal(variance.sqrt(), COMPOSITE_RETURN_QUANTUM)


def calculate_annual_dispersion(
    members: Sequence[AnnualMemberReturn], *, method: AnnualDispersionMethod
) -> Decimal | None:
    ordered = _qualified_members(members)
    try:
        with localcontext() as context:
            context.prec = 60
            context.rounding = ROUND_HALF_EVEN
            context.Emax = 128
            context.Emin = -128
            if method == "EQUAL_WEIGHT_SAMPLE_STDDEV":
                return _sample_standard_deviation([item.annual_return for item in ordered])
            if method != "YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV":
                raise AnnualDispersionDomainError("Dispersion method is unsupported")
            return _asset_weighted_population_dispersion(ordered)
    except DecimalException as exc:
        raise AnnualDispersionDomainError("Dispersion exceeds the Decimal domain") from exc
