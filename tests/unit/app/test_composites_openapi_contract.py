from __future__ import annotations

from main import app


def test_composite_twr_openapi_documents_persisted_fact_contract() -> None:
    spec = app.openapi()

    composite_post = spec["paths"]["/performance/composites/twr"]["post"]
    assert "composite TWR from persisted member-return facts" in composite_post["description"]
    assert "does not accept ad hoc member returns" in composite_post["description"]
    assert "hidden request-time portfolio TWR fan-out" in composite_post["description"]
    assert "404" in composite_post["responses"]
    assert "422" in composite_post["responses"]
    assert (
        composite_post["responses"]["404"]["content"]["application/json"]["example"]["detail"]["code"]
        == "COMPOSITE_NOT_FOUND"
    )
    no_facts_example = composite_post["responses"]["422"]["content"]["application/json"]["examples"][
        "no_persisted_member_return_facts"
    ]["value"]
    assert no_facts_example["detail"]["code"] == "NO_MEMBER_RETURN_FACTS"
    invalid_window_example = composite_post["responses"]["422"]["content"]["application/json"]["examples"][
        "invalid_window"
    ]["value"]
    assert "period_end cannot be before period_start" in invalid_window_example["detail"][0]["msg"]

    request_schema = spec["components"]["schemas"]["CompositeTWRRequest"]
    assert "calculation_id" in request_schema["properties"]
    assert (
        "Composite identifier to calculate from persisted member-return facts"
        in request_schema["properties"]["composite_id"]["description"]
    )

    response_schema = spec["components"]["schemas"]["CompositeTWRResponse"]
    assert "Geometrically linked composite TWR" in response_schema["properties"]["cumulative_return"]["description"]
    period_schema = spec["components"]["schemas"]["CompositePeriodResultResponse"]
    assert (
        "Equal-weight sample standard deviation"
        in period_schema["properties"]["dispersion_equal_weight"]["description"]
    )
    member_schema = spec["components"]["schemas"]["CompositeMemberContributionResponse"]
    assert "Beginning-asset member weight" in member_schema["properties"]["beginning_asset_weight"]["description"]

    inspection_post = spec["paths"]["/performance/composites/inspect"]["post"]
    assert (
        inspection_post["responses"]["404"]["content"]["application/json"]["example"]["detail"]["code"]
        == "COMPOSITE_NOT_FOUND"
    )
