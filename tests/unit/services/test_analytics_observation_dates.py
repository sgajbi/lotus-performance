from datetime import date

from app.services.analytics_observation_dates import latest_observation_date


def test_latest_observation_date_normalizes_mixed_date_values():
    assert latest_observation_date(["2026-03-29", date(2026, 3, 31), None, "2026-03-30T12:00:00Z"]) == date(
        2026,
        3,
        31,
    )


def test_latest_observation_date_returns_none_when_no_values_exist():
    assert latest_observation_date([None]) is None
