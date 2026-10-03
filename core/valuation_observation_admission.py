from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence, TypeVar

ECONOMIC_FIELDS: tuple[str, ...] = (
    "begin_mv",
    "bod_cf",
    "eod_cf",
    "mgmt_fees",
    "end_mv",
)
_OPTIONAL_ECONOMIC_FIELDS = frozenset({"bod_cf", "eod_cf", "mgmt_fees"})

ValuationObservation = TypeVar("ValuationObservation", bound=Mapping[str, object])


class ValuationObservationAdmissionError(ValueError):
    """Raised when valuation observations cannot establish one authoritative daily state."""


def finite_decimal_value(value: object, *, field_name: str) -> Decimal:
    """Return a finite decimal representation without changing the public numeric contract."""
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValuationObservationAdmissionError(f"{field_name} must be a valid finite number") from exc
    if not decimal_value.is_finite():
        raise ValuationObservationAdmissionError(f"{field_name} must be a finite number")
    return decimal_value


def normalize_valuation_observation_date(value: object) -> date:
    """Normalize supported date and ISO date-time representations to their business date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValuationObservationAdmissionError("perf_date must be a valid date")

    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise ValuationObservationAdmissionError("perf_date must be a valid date") from exc


def admit_valuation_observations(
    observations: Sequence[ValuationObservation],
) -> list[ValuationObservation]:
    """Keep first identical daily observation and reject contradictory daily economics."""
    admitted: list[ValuationObservation] = []
    signature_by_date: dict[date, tuple[Decimal, ...]] = {}

    for observation in observations:
        observation_date = normalize_valuation_observation_date(observation.get("perf_date"))
        signature = _economic_signature(observation)
        previous_signature = signature_by_date.get(observation_date)
        if previous_signature is None:
            signature_by_date[observation_date] = signature
            admitted.append(observation)
            continue
        if previous_signature == signature:
            continue

        conflicting_fields = [
            field_name
            for field_name, previous_value, current_value in zip(
                ECONOMIC_FIELDS,
                previous_signature,
                signature,
                strict=True,
            )
            if previous_value != current_value
        ]
        raise ValuationObservationAdmissionError(
            "conflicting valuation observations for perf_date "
            f"{observation_date.isoformat()}: {', '.join(conflicting_fields)}"
        )

    return admitted


def _economic_signature(observation: Mapping[str, object]) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    for field_name in ECONOMIC_FIELDS:
        value = observation.get(field_name)
        if value is None and field_name in _OPTIONAL_ECONOMIC_FIELDS:
            value = 0
        if value is None:
            raise ValuationObservationAdmissionError(f"{field_name} is required")
        values.append(finite_decimal_value(value, field_name=field_name))
    return tuple(values)
