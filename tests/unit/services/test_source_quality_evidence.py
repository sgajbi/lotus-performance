from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from app.services.source_quality_evidence import (
    _has_stale_source_observations,
    _record_source_quality_observation,
    _record_source_values_by_date,
    _summarize_source_quality_observations,
    _unsupported_cashflow_count,
    build_portfolio_source_quality_evidence,
)


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


def test_unsupported_cashflow_count_ignores_non_flow_values_and_counts_unsupported_taxonomy():
    assert (
        _unsupported_cashflow_count(
            [
                {"cash_flow_type": "external_flow"},
                {"cash_flow_type": "dividend"},
                "not-a-flow",
            ]
        )
        == 1
    )
    assert _unsupported_cashflow_count("not-a-list") == 0


def test_source_quality_observation_summary_counts_invalid_numeric_values_and_classifications():
    summary = _summarize_source_quality_observations(
        [
            {
                "valuation_date": "2026-03-31",
                "beginning_market_value": "not-a-number",
                "ending_market_value": "1010",
                "source_classification": "official",
                "cash_flows": [{"cash_flow_type": "dividend"}],
            },
            {
                "valuation_date": "2026-04-01",
                "beginning_market_value": "1010",
                "ending_market_value": "1012",
                "source_classification": 123,
                "cash_flows": [{"cash_flow_type": "external_flow"}],
            },
        ]
    )

    assert summary.skipped_observation_count == 1
    assert summary.unsupported_cashflow_count == 1
    assert summary.source_classifications == {"official": 1}
    assert summary.normalized_dates == [date(2026, 3, 31), date(2026, 4, 1)]
    assert summary.values_by_date == {
        "2026-03-31": set(),
        "2026-04-01": {(Decimal("1010"), Decimal("1012"))},
    }


def test_record_source_quality_observation_preserves_invalid_numeric_date_and_classification():
    source_classifications: Counter[str] = Counter()
    values_by_date: dict[str, set[tuple[Decimal, Decimal]]] = defaultdict(set)
    normalized_dates: list[date] = []

    skipped_count = _record_source_quality_observation(
        {
            "valuation_date": "2026-03-31",
            "beginning_market_value": "not-a-number",
            "ending_market_value": "1010",
            "source_classification": "official",
        },
        source_classifications=source_classifications,
        values_by_date=values_by_date,
        normalized_dates=normalized_dates,
    )

    assert skipped_count == 1
    assert source_classifications == {"official": 1}
    assert normalized_dates == [date(2026, 3, 31)]
    assert values_by_date == {"2026-03-31": set()}


def test_record_source_values_by_date_projects_valid_market_values():
    values_by_date: dict[str, set[tuple[Decimal, Decimal]]] = defaultdict(set)
    normalized_dates: list[date] = []

    skipped_count = _record_source_values_by_date(
        valuation_date="2026-03-31",
        beginning_market_value="1000.25",
        ending_market_value="1010.50",
        values_by_date=values_by_date,
        normalized_dates=normalized_dates,
    )

    assert skipped_count == 0
    assert normalized_dates == [date(2026, 3, 31)]
    assert values_by_date == {"2026-03-31": {(Decimal("1000.25"), Decimal("1010.50"))}}


def test_has_stale_source_observations_requires_both_dates_and_lagging_source():
    assert not _has_stale_source_observations(
        latest_observation_date=None,
        report_end_date=date(2026, 4, 1),
    )
    assert not _has_stale_source_observations(
        latest_observation_date=date(2026, 3, 31),
        report_end_date=None,
    )
    assert not _has_stale_source_observations(
        latest_observation_date=date(2026, 4, 1),
        report_end_date=date(2026, 4, 1),
    )
    assert _has_stale_source_observations(
        latest_observation_date=date(2026, 3, 31),
        report_end_date=date(2026, 4, 1),
    )
