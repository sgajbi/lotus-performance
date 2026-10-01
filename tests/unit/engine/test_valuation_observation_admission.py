from datetime import date, datetime, timezone

import pytest

from core.valuation_observation_admission import (
    ValuationObservationAdmissionError,
    admit_valuation_observations,
    finite_decimal_value,
    normalize_valuation_observation_date,
)


def test_finite_decimal_value_rejects_non_numeric_text() -> None:
    with pytest.raises(ValuationObservationAdmissionError, match="valid finite number"):
        finite_decimal_value("not-a-number", field_name="begin_mv")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2025, 1, 2, 23, 30, tzinfo=timezone.utc), date(2025, 1, 2)),
        (date(2025, 1, 2), date(2025, 1, 2)),
        ("2025-01-02T23:30:00Z", date(2025, 1, 2)),
    ],
)
def test_normalize_valuation_observation_date_accepts_supported_types(value: object, expected: date) -> None:
    assert normalize_valuation_observation_date(value) == expected


@pytest.mark.parametrize("value", [None, "not-a-date"])
def test_normalize_valuation_observation_date_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValuationObservationAdmissionError, match="perf_date must be a valid date"):
        normalize_valuation_observation_date(value)


def test_admit_valuation_observations_requires_boundary_market_values() -> None:
    with pytest.raises(ValuationObservationAdmissionError, match="end_mv is required"):
        admit_valuation_observations([{"perf_date": "2025-01-02", "begin_mv": 100}])
