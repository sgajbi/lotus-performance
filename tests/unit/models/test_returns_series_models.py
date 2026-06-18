from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.returns_series import (
    BenchmarkSpec,
    InputMode,
    ReturnsRelativePeriod,
    ReturnsWindow,
    ReturnsWindowMode,
    StatefulInput,
    StatelessInput,
    _require_selected_stateless_series,
    _returns_series_stateless_benchmark_override_issue,
    _returns_window_with_normalized_period_alias,
    _validate_explicit_returns_window,
    _validate_relative_returns_window,
    _validate_stateful_returns_series_input_envelope,
    _validate_stateless_returns_series_input_envelope,
)


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


def test_returns_window_validation_helpers_preserve_explicit_and_relative_policy():
    _validate_explicit_returns_window(from_date=date(2026, 2, 24), to_date=date(2026, 2, 27))
    _validate_relative_returns_window(period=ReturnsRelativePeriod.YEAR, year=2026)

    with pytest.raises(ValueError, match="from_date cannot be after to_date"):
        _validate_explicit_returns_window(from_date=date(2026, 2, 27), to_date=date(2026, 2, 24))
    with pytest.raises(ValueError, match="year is required when period=YEAR"):
        _validate_relative_returns_window(period=ReturnsRelativePeriod.YEAR, year=None)


def test_returns_window_period_alias_helper_normalizes_only_legacy_string_aliases():
    aliases = {"THREE_YEAR": "3Y"}

    assert _returns_window_with_normalized_period_alias(
        {"mode": "RELATIVE", "period": "THREE_YEAR"},
        period_aliases=aliases,
    ) == {"mode": "RELATIVE", "period": "3Y"}
    assert _returns_window_with_normalized_period_alias(
        {"mode": "RELATIVE", "period": "3Y"},
        period_aliases=aliases,
    ) == {"mode": "RELATIVE", "period": "3Y"}
    assert _returns_window_with_normalized_period_alias(
        {"mode": "RELATIVE", "period": 3},
        period_aliases=aliases,
    ) == {"mode": "RELATIVE", "period": 3}
    assert _returns_window_with_normalized_period_alias("not-a-dict", period_aliases=aliases) == "not-a-dict"


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


def test_returns_series_request_rejects_mixed_input_envelopes():
    from app.models.returns_series import ReturnsSeriesRequest

    payload = _base_payload()
    payload["stateful_input"] = {}
    with pytest.raises(ValidationError, match="stateful_input must be null when input_mode=stateless"):
        ReturnsSeriesRequest.model_validate(payload)

    stateful_payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
        "input_mode": "stateful",
        "stateful_input": {},
        "stateless_input": {
            "portfolio_returns": [
                {"date": "2026-02-24", "return_value": "0.0010"},
            ]
        },
    }
    with pytest.raises(ValidationError, match="stateless_input must be null when input_mode=stateful"):
        ReturnsSeriesRequest.model_validate(stateful_payload)


def test_returns_series_input_envelope_helpers_preserve_mode_policy():
    stateless_input = StatelessInput.model_validate(
        {"portfolio_returns": [{"date": "2026-02-24", "return_value": "0.0010"}]}
    )
    stateful_input = StatefulInput()

    _validate_stateless_returns_series_input_envelope(stateless_input=stateless_input, stateful_input=None)
    _validate_stateful_returns_series_input_envelope(stateless_input=None, stateful_input=stateful_input)

    with pytest.raises(ValueError, match="stateless_input is required when input_mode=stateless"):
        _validate_stateless_returns_series_input_envelope(stateless_input=None, stateful_input=None)
    with pytest.raises(ValueError, match="stateful_input must be null when input_mode=stateless"):
        _validate_stateless_returns_series_input_envelope(
            stateless_input=stateless_input,
            stateful_input=stateful_input,
        )
    with pytest.raises(ValueError, match="stateful_input is required when input_mode=stateful"):
        _validate_stateful_returns_series_input_envelope(stateless_input=None, stateful_input=None)
    with pytest.raises(ValueError, match="stateless_input must be null when input_mode=stateful"):
        _validate_stateful_returns_series_input_envelope(
            stateless_input=stateless_input,
            stateful_input=stateful_input,
        )


def test_require_selected_stateless_series_preserves_selected_series_policy():
    stateless_input = StatelessInput.model_validate(
        {"portfolio_returns": [{"date": "2026-02-24", "return_value": "0.0010"}]}
    )

    _require_selected_stateless_series(
        selected=False,
        stateless_input=None,
        values=None,
        message="not used",
    )

    with pytest.raises(ValueError, match="benchmark_returns are required"):
        _require_selected_stateless_series(
            selected=True,
            stateless_input=stateless_input,
            values=stateless_input.benchmark_returns,
            message="benchmark_returns are required when include_benchmark=true in stateless mode",
        )
    with pytest.raises(ValueError, match="risk_free_returns are required"):
        _require_selected_stateless_series(
            selected=True,
            stateless_input=None,
            values=None,
            message="risk_free_returns are required when include_risk_free=true in stateless mode",
        )


def test_returns_series_request_requires_stateful_input_when_stateful_mode():
    from app.models.returns_series import ReturnsSeriesRequest

    stateful_payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-27",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
        "input_mode": "stateful",
    }

    with pytest.raises(ValidationError, match="stateful_input is required when input_mode=stateful"):
        ReturnsSeriesRequest.model_validate(stateful_payload)


def test_returns_series_request_generates_calculation_id_by_default():
    from app.models.returns_series import ReturnsSeriesRequest

    request = ReturnsSeriesRequest.model_validate(_base_payload())

    assert request.calculation_id is not None


def test_returns_series_benchmark_spec_defaults_to_calculated_return_source():
    from app.models.returns_series import BenchmarkSpec

    benchmark = BenchmarkSpec.model_validate({})

    assert benchmark.return_source.value == "calculated"


def test_returns_series_rejects_stateful_only_benchmark_config_in_stateless_mode():
    from app.models.returns_series import ReturnsSeriesRequest

    payload = _base_payload()
    payload["benchmark"] = {"benchmark_id": "BMK_1"}

    with pytest.raises(
        ValidationError,
        match="benchmark.benchmark_id is only supported in stateful mode for returns-series",
    ):
        ReturnsSeriesRequest.model_validate(payload)

    payload = _base_payload()
    payload["benchmark"] = {"return_source": "vendor_series"}

    with pytest.raises(
        ValidationError,
        match="benchmark.return_source is only supported in stateful mode for returns-series",
    ):
        ReturnsSeriesRequest.model_validate(payload)


def test_returns_series_stateless_benchmark_override_issue_preserves_mode_policy():
    assert (
        _returns_series_stateless_benchmark_override_issue(
            input_mode=InputMode.STATEFUL,
            benchmark=BenchmarkSpec.model_validate({"benchmark_id": "BMK_1"}),
        )
        is None
    )
    assert (
        _returns_series_stateless_benchmark_override_issue(
            input_mode=InputMode.STATELESS,
            benchmark=BenchmarkSpec.model_validate({}),
        )
        is None
    )
    assert (
        _returns_series_stateless_benchmark_override_issue(
            input_mode=InputMode.STATELESS,
            benchmark=BenchmarkSpec.model_validate({"benchmark_id": "BMK_1"}),
        )
        == "benchmark.benchmark_id is only supported in stateful mode for returns-series"
    )
    assert (
        _returns_series_stateless_benchmark_override_issue(
            input_mode=InputMode.STATELESS,
            benchmark=BenchmarkSpec.model_validate({"return_source": "vendor_series"}),
        )
        == "benchmark.return_source is only supported in stateful mode for returns-series"
    )


def test_returns_series_allows_default_benchmark_override_in_stateless_mode():
    from app.models.returns_series import ReturnsSeriesRequest

    payload = _base_payload()
    payload["benchmark"] = {}

    request = ReturnsSeriesRequest.model_validate(payload)

    assert request.benchmark is not None
    assert request.benchmark.return_source.value == "calculated"
