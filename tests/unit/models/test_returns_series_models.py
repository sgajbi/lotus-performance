from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.returns_series import ReturnsWindow, ReturnsWindowMode


def _base_payload() -> dict:
    return {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
        "input_mode": "stateless",
        "stateless_input": {
            "portfolio_returns": [
                {"date": "2026-02-24", "return_value": "0.0010"},
                {"date": "2026-02-25", "return_value": "0.0012"},
            ]
        },
    }


def test_returns_window_validation_error_paths():
    with pytest.raises(ValidationError, match="from_date and to_date are required when mode=EXPLICIT"):
        ReturnsWindow.model_validate({"mode": "EXPLICIT"})

    with pytest.raises(ValidationError, match="from_date cannot be after to_date"):
        ReturnsWindow.model_validate({"mode": "EXPLICIT", "from_date": "2026-02-28", "to_date": "2026-02-27"})

    with pytest.raises(ValidationError, match="period is required when mode=RELATIVE"):
        ReturnsWindow.model_validate({"mode": "RELATIVE"})

    with pytest.raises(ValidationError, match="year is required when period=YEAR"):
        ReturnsWindow.model_validate({"mode": "RELATIVE", "period": "YEAR"})

    window = ReturnsWindow.model_validate({"mode": "RELATIVE", "period": "YEAR", "year": 2025})
    assert window.mode == ReturnsWindowMode.RELATIVE
    assert window.year == 2025


def test_returns_series_request_requires_stateless_input_when_stateless_mode():
    from app.models.returns_series import ReturnsSeriesRequest

    payload = _base_payload()
    payload.pop("stateless_input")
    with pytest.raises(ValidationError, match="stateless_input is required when input_mode=stateless"):
        ReturnsSeriesRequest.model_validate(payload)


def test_returns_series_request_requires_benchmark_returns_when_selected():
    from app.models.returns_series import ReturnsSeriesRequest

    payload = _base_payload()
    payload["series_selection"] = {"include_benchmark": True}
    with pytest.raises(
        ValidationError, match="benchmark_returns are required when include_benchmark=true in stateless mode"
    ):
        ReturnsSeriesRequest.model_validate(payload)


def test_returns_series_request_requires_risk_free_returns_when_selected():
    from app.models.returns_series import ReturnsSeriesRequest

    payload = _base_payload()
    payload["series_selection"] = {"include_risk_free": True}
    with pytest.raises(
        ValidationError, match="risk_free_returns are required when include_risk_free=true in stateless mode"
    ):
        ReturnsSeriesRequest.model_validate(payload)
