from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest
from app.models.mwr_requests import CashFlow


def test_mwr_analytics_request_builds_stateless_request_from_nested_input():
    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "portfolio_id": "MWR_STATELESS",
            "as_of": "2025-12-31",
            "input_mode": "stateless",
            "stateless_input": {
                "begin_mv": 1000,
                "end_mv": 1050,
                "cash_flows": [{"amount": 25, "date": "2025-06-30"}],
            },
        }
    )

    stateless = request.to_stateless_mwr_request()

    assert stateless.begin_mv == 1000
    assert stateless.end_mv == 1050
    assert len(stateless.cash_flows) == 1


def test_mwr_analytics_request_rejects_stateful_input_in_stateless_mode():
    try:
        MoneyWeightedReturnAnalyticsRequest.model_validate(
            {
                "portfolio_id": "MWR_BAD",
                "as_of": "2025-12-31",
                "input_mode": "stateless",
                "stateful_input": {
                    "window_start_date": "2025-01-01",
                },
                "stateless_input": {
                    "begin_mv": 1000,
                    "end_mv": 1050,
                    "cash_flows": [{"amount": 25, "date": "2025-06-30"}],
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        assert "stateful_input must be null when input_mode=stateless" in str(exc)
    else:
        raise AssertionError("Expected request validation to fail for stateful_input in stateless mode.")


def test_mwr_analytics_request_rejects_missing_stateless_payload():
    try:
        MoneyWeightedReturnAnalyticsRequest.model_validate(
            {
                "portfolio_id": "MWR_BAD",
                "as_of": "2025-12-31",
                "input_mode": "stateless",
            }
        )
    except Exception as exc:  # noqa: BLE001
        assert "stateless_input or legacy begin_mv/end_mv/cash_flows is required" in str(exc)
    else:
        raise AssertionError("Expected request validation to fail without a stateless payload.")


def test_mwr_analytics_request_rejects_missing_stateful_payload():
    try:
        MoneyWeightedReturnAnalyticsRequest.model_validate(
            {
                "portfolio_id": "MWR_BAD",
                "as_of": "2025-12-31",
                "input_mode": "stateful",
            }
        )
    except Exception as exc:  # noqa: BLE001
        assert "stateful_input is required when input_mode=stateful" in str(exc)
    else:
        raise AssertionError("Expected request validation to fail without a stateful payload.")


def test_mwr_analytics_request_rejects_partial_legacy_stateless_payload():
    try:
        MoneyWeightedReturnAnalyticsRequest.model_validate(
            {
                "portfolio_id": "MWR_BAD",
                "as_of": "2025-12-31",
                "begin_mv": 1000,
                "end_mv": 1050,
            }
        )
    except Exception as exc:  # noqa: BLE001
        assert "begin_mv, end_mv, and cash_flows must be provided together" in str(exc)
    else:
        raise AssertionError("Expected request validation to fail for partial legacy payload.")


def test_mwr_analytics_request_rejects_ambiguous_stateless_payload():
    try:
        MoneyWeightedReturnAnalyticsRequest.model_validate(
            {
                "portfolio_id": "MWR_BAD",
                "as_of": "2025-12-31",
                "stateless_input": {
                    "begin_mv": 1000,
                    "end_mv": 1050,
                    "cash_flows": [{"amount": 25, "date": "2025-06-30"}],
                },
                "begin_mv": 1000,
                "end_mv": 1050,
                "cash_flows": [{"amount": 25, "date": "2025-06-30"}],
            }
        )
    except Exception as exc:  # noqa: BLE001
        assert "Provide either stateless_input or legacy begin_mv/end_mv/cash_flows" in str(exc)
    else:
        raise AssertionError("Expected request validation to fail for ambiguous stateless payload.")


def test_mwr_analytics_request_rejects_stateful_payload_shape_conflicts():
    try:
        MoneyWeightedReturnAnalyticsRequest.model_validate(
            {
                "portfolio_id": "MWR_BAD",
                "as_of": "2025-12-31",
                "input_mode": "stateful",
                "stateful_input": {
                    "window_start_date": "2025-01-01",
                },
                "stateless_input": {
                    "begin_mv": 1000,
                    "end_mv": 1050,
                    "cash_flows": [{"amount": 25, "date": "2025-06-30"}],
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        assert "stateless_input must be null when input_mode=stateful" in str(exc)
    else:
        raise AssertionError("Expected request validation to fail for stateful/stateless conflict.")

    try:
        MoneyWeightedReturnAnalyticsRequest.model_validate(
            {
                "portfolio_id": "MWR_BAD",
                "as_of": "2025-12-31",
                "input_mode": "stateful",
                "stateful_input": {
                    "window_start_date": "2025-01-01",
                },
                "begin_mv": 1000,
                "end_mv": 1050,
                "cash_flows": [{"amount": 25, "date": "2025-06-30"}],
            }
        )
    except Exception as exc:  # noqa: BLE001
        assert "begin_mv, end_mv, and cash_flows must be null when input_mode=stateful" in str(exc)
    else:
        raise AssertionError("Expected request validation to fail for stateful legacy payload.")


def test_mwr_analytics_request_to_stateless_prefers_explicit_override():
    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "portfolio_id": "MWR_STATELESS",
            "as_of": "2025-12-31",
            "input_mode": "stateless",
            "stateless_input": {
                "begin_mv": 1000,
                "end_mv": 1050,
                "cash_flows": [{"amount": 25, "date": "2025-06-30"}],
            },
        }
    )

    stateless = request.to_stateless_mwr_request(
        begin_mv=2000,
        end_mv=2100,
        cash_flows=[CashFlow.model_validate({"amount": 50, "date": "2025-07-31"})],
        start_date="2025-01-01",
    )

    assert stateless.begin_mv == 2000
    assert stateless.end_mv == 2100
    assert stateless.cash_flows[0].amount == 50
    assert str(stateless.start_date) == "2025-01-01"


def test_mwr_analytics_request_to_stateless_fails_without_stateless_payload():
    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "portfolio_id": "MWR_STATEFUL",
            "as_of": "2025-12-31",
            "input_mode": "stateful",
            "stateful_input": {
                "window_start_date": "2025-01-01",
            },
        }
    )

    try:
        request.to_stateless_mwr_request()
    except ValueError as exc:
        assert "No stateless MWR inputs are available" in str(exc)
    else:
        raise AssertionError("Expected stateless conversion to fail without a stateless payload.")
