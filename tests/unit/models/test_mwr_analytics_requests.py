from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest


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
