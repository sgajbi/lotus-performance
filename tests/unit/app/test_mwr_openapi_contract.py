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
    assert "period Dietz return" in mwr_post["description"]
    assert "200" in mwr_post["responses"]
    assert "422" in mwr_post["responses"]
