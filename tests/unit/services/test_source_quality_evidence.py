from datetime import date

from app.services.source_quality_evidence import build_portfolio_source_quality_evidence


def test_source_quality_evidence_captures_stateful_quality_warnings():
    evidence = build_portfolio_source_quality_evidence(
        observations=[
            {
                "valuation_date": "2026-03-30",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
                "source_classification": "official",
                "cash_flows": [{"cash_flow_type": "dividend", "amount": "25", "timing": "eod"}],
            },
            {
                "valuation_date": "2026-03-30",
                "beginning_market_value": "1000",
                "ending_market_value": "1009",
                "source_classification": "manual_adjustment",
                "cash_flows": [],
            },
            {
                "valuation_date": "2026-03-31",
                "beginning_market_value": None,
                "ending_market_value": "1015",
                "source_classification": "official",
            },
        ],
        valid_valuation_point_count=2,
        report_end_date=date(2026, 4, 1),
        input_mode="stateful",
        source_owner="lotus-core",
        source_product="PortfolioTimeseriesInput",
    )

    assert evidence.source_owner == "lotus-core"
    assert evidence.source_product == "PortfolioTimeseriesInput"
    assert evidence.input_mode == "stateful"
    assert evidence.quality_state == "stale"
    assert evidence.observation_count == 3
    assert evidence.valid_valuation_point_count == 2
    assert evidence.skipped_observation_count == 1
    assert evidence.unsupported_cashflow_count == 1
    assert evidence.source_conflict_count == 1
    assert evidence.latest_observation_date == date(2026, 3, 30)
    assert evidence.warnings == [
        "MISSING_VALUATION_POINTS",
        "UNSUPPORTED_CASHFLOW_LABELS",
        "SOURCE_DATE_CONFLICTS",
        "STALE_SOURCE_OBSERVATIONS",
    ]
    assert evidence.source_classification_counts == {"manual_adjustment": 1, "official": 2}


def test_source_quality_evidence_marks_clean_stateful_source():
    evidence = build_portfolio_source_quality_evidence(
        observations=[
            {
                "valuation_date": "2026-03-31",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
                "cash_flows": [{"cash_flow_type": "external_flow", "amount": "25", "timing": "bod"}],
            }
        ],
        valid_valuation_point_count=1,
        report_end_date=date(2026, 3, 31),
        input_mode="stateful",
        source_owner="lotus-core",
        source_product="PortfolioTimeseriesInput",
    )

    assert evidence.quality_state == "clean"
    assert evidence.warnings == []


def test_source_quality_evidence_marks_degraded_malformed_source_without_staleness():
    evidence = build_portfolio_source_quality_evidence(
        observations=[
            {
                "valuation_date": "not-a-date",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
                "cash_flows": ["not-a-dict-flow"],
            },
            {
                "valuation_date": "2026-03-31",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
                "cash_flows": [],
            },
        ],
        valid_valuation_point_count=1,
        report_end_date=date(2026, 3, 31),
        input_mode="stateful",
        source_owner="lotus-core",
        source_product="PortfolioTimeseriesInput",
    )

    assert evidence.quality_state == "degraded"
    assert evidence.skipped_observation_count == 1
    assert evidence.latest_observation_date == date(2026, 3, 31)
    assert evidence.warnings == ["MISSING_VALUATION_POINTS"]
