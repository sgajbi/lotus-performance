import pytest

from app.services.portfolio_source_service import parse_stateful_portfolio_timeseries_payload


def test_parse_stateful_portfolio_timeseries_payload_filters_observations_and_preserves_identity():
    source = parse_stateful_portfolio_timeseries_payload(
        {
            "portfolio_open_date": "2026-01-15",
            "portfolio_currency": "USD",
            "reporting_currency": "SGD",
            "observations": [
                {"valuation_date": "2026-05-29", "ending_market_value": "1000.00"},
                "invalid-row",
                {"valuation_date": "2026-05-30", "ending_market_value": "1010.00"},
            ],
        },
        require_open_date=True,
    )

    assert source.portfolio_open_date == "2026-01-15"
    assert source.portfolio_currency == "USD"
    assert source.reporting_currency == "SGD"
    assert source.observations == [
        {"valuation_date": "2026-05-29", "ending_market_value": "1000.00"},
        {"valuation_date": "2026-05-30", "ending_market_value": "1010.00"},
    ]


def test_parse_stateful_portfolio_timeseries_payload_rejects_missing_required_open_date():
    with pytest.raises(ValueError, match="Stateful source missing portfolio_open_date"):
        parse_stateful_portfolio_timeseries_payload(
            {
                "observations": [{"valuation_date": "2026-05-29"}],
            },
            require_open_date=True,
        )


def test_parse_stateful_portfolio_timeseries_payload_allows_optional_open_date_and_ignores_bad_scalars():
    source = parse_stateful_portfolio_timeseries_payload(
        {
            "portfolio_open_date": None,
            "portfolio_currency": 123,
            "reporting_currency": ["USD"],
            "observations": {"not": "a-list"},
        },
        require_open_date=False,
    )

    assert source.portfolio_open_date is None
    assert source.portfolio_currency is None
    assert source.reporting_currency is None
    assert source.observations == []
