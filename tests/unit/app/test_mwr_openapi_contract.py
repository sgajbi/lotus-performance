from main import app


def test_mwr_openapi_explains_capital_timing_purpose_and_modes() -> None:
    spec = app.openapi()

    mwr_post = spec["paths"]["/performance/mwr"]["post"]

    assert "money-weighted return" in mwr_post["description"].lower()
    assert "investor capital-timing lens" in mwr_post["description"]
    assert 'input_mode="stateless"' in mwr_post["description"]
    assert 'input_mode="stateful"' in mwr_post["description"]
    assert "query-control-plane portfolio timeseries" in mwr_post["description"]
    assert "cross-observation carry-forward capital breaks" in mwr_post["description"]
    assert "annual IRR" in mwr_post["description"]
    assert "dated cash-flow weights" in mwr_post["description"]
    assert "midpoint Dietz period return" in mwr_post["description"]
    assert "200" in mwr_post["responses"]
    assert "422" in mwr_post["responses"]
    response_schema = spec["components"]["schemas"]["MoneyWeightedReturnResponse"]
    assert "calculation_supportability" in response_schema["properties"]
    assert "reporting_currency" in response_schema["properties"]
    assert "currency_evidence" in response_schema["properties"]
    assert "source freshness" in response_schema["properties"]["calculation_supportability"]["description"]
    evidence_schema = spec["components"]["schemas"]["MWRCurrencyEvidence"]
    assert "market_values_used" in evidence_schema["properties"]
    assert "cashflow_evidence" in evidence_schema["properties"]
    assert "conversion_evidence_status" in evidence_schema["properties"]
