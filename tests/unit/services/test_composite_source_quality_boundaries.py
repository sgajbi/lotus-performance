"""Upstream completeness and return-observation boundaries used by Composite sources."""

from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services import returns_series_service as returns
from app.services import stateful_input_service as stateful
from core.errors import APIError


def accumulator():
    return stateful._PerformanceComponentEconomicsAccumulator(
        observed_component_families=set(), supported_component_families=set(), missing_component_families=set()
    )


@pytest.mark.parametrize("supportability", [None, [], {}, {"state": "READY"}, {"reason": "complete"}])
def test_missing_component_supportability_cannot_become_complete_economics(supportability):
    collected = accumulator()
    stateful._record_performance_component_economics_payload(
        accumulator=collected, payload=dict(rows=[], supportability=supportability)
    )
    assert collected.unavailable_chunk_count == 1
    assert collected.source_verdicts == []


@pytest.mark.parametrize(
    "verdicts,expected",
    [
        ([], ("UNAVAILABLE", "PERFORMANCE_COMPONENT_ECONOMICS_UNAVAILABLE")),
        ([{"state": "DEGRADED", "reason": "partial"}], ("UNAVAILABLE", "partial")),
        ([{"state": "UNKNOWN", "reason": "unknown"}], ("UNAVAILABLE", "PERFORMANCE_COMPONENT_ECONOMICS_UNAVAILABLE")),
        (
            [
                {"state": "DEGRADED", "reason": "PERFORMANCE_COMPONENT_ECONOMICS_PAGE_PARTIAL"},
                {"state": "READY", "reason": "complete"},
            ],
            ("READY", "complete"),
        ),
    ],
)
def test_only_complete_final_page_can_finish_component_source(verdicts, expected):
    collected = accumulator()
    collected.source_verdicts = verdicts
    assert stateful._performance_component_economics_chunk_state_reason(collected) == expected


def test_failed_and_unclassified_chunks_remain_unavailable_in_aggregate():
    result = stateful._performance_component_economics_accumulator([(503, {}), (200, {"supportability": []})])
    assert result.unavailable_chunk_count == 2
    assert result.ready_chunk_count == 0
    assert result.source_row_count == 0


def test_component_totals_do_not_manufacture_amounts_for_malformed_source_rows():
    totals = [
        dict(component_family="fee", currency="USD", amount="1.25", evidence_count=1),
        dict(component_family="fee", currency="USD", amount="2.75", evidence_count=2),
        dict(component_family="fee", currency="USD", amount="not-numeric"),
        dict(currency="USD", amount="9"),
    ]
    assert stateful._merge_performance_component_economics_totals(totals) == [
        dict(component_family="fee", currency="USD", amount="4.00", evidence_count=3)
    ]
    assert stateful._dict_list_payload_items_from_payload({"rows": {}}, "rows") == []
    assert stateful._position_retrieval_count_total([(200, {})], "row_count") is None
    assert stateful._position_retrieval_count_total([(200, {"retrieval_metadata": {"row_count": 0}})], "row_count") == 0


def test_source_owned_position_grain_precedes_derived_position_identity():
    row = dict(position_grain_id="source-grain", position_id="position", security_id="security")
    projected = stateful._position_row_with_source_key(row)
    assert projected["source_position_key"] == "source-grain"
    assert "source_position_key" not in row


@pytest.mark.parametrize("latest", [date(2026, 1, 5), datetime(2026, 1, 5, 12), "2026-01-05"])
def test_latest_return_source_date_accepts_supported_source_representations(latest):
    frame = pd.DataFrame({"date": pd.Series([latest], dtype=object)})
    assert returns._latest_series_date(frame) == date(2026, 1, 5)
    assert returns._latest_series_date(None) is None
    assert returns._latest_series_date(pd.DataFrame()) is None


def test_non_trading_window_uses_declared_end_without_inventing_observations():
    start, end = pd.Timestamp("2026-01-03"), pd.Timestamp("2026-01-04")
    assert (
        returns._last_required_source_observation_date(
            start=start, end=end, calendar_policy=returns.CalendarPolicy.CALENDAR
        )
        == end.date()
    )
    policy = next(policy for policy in returns.CalendarPolicy if policy != returns.CalendarPolicy.CALENDAR)
    assert returns._last_required_source_observation_date(start=start, end=end, calendar_policy=policy) == end.date()
    window = SimpleNamespace(start_date=start.date(), end_date=end.date())
    assert (
        returns._last_required_observation_date(
            window, frequency=returns.ReturnsFrequency.DAILY, calendar_policy=policy
        )
        == end.date()
    )


def test_no_added_dates_produces_no_fill_evidence():
    source = pd.DataFrame({"date": pd.to_datetime(["2026-01-05"]), "return_value": [0.1]})
    method = next(method for method in returns.FillMethod if method != returns.FillMethod.NONE)
    assert (
        returns._fill_evidence_for_side_series(
            series_type="benchmark", source_df=source, returned_df=source.copy(), fill_method=method
        )
        is None
    )
    assert returns._valid_return_dates(source.drop(columns="return_value")).equals(source["date"])


def test_absent_stateless_inputs_and_optional_risk_free_never_become_observed_zero():
    request = SimpleNamespace(stateless_input=None, series_selection=SimpleNamespace(include_risk_free=True))
    assert returns._stateless_risk_free_source_quality_from_request(request) is None
    request.stateless_input = SimpleNamespace(risk_free_returns=None)
    assert returns._stateless_risk_free_source_quality_from_request(request) is None
    request.stateless_input = None
    with pytest.raises(APIError) as error:
        returns._prepare_stateless_returns_series_freshness_frames(request=request, resolved_window=None)
    assert error.value.status_code == 400


def test_gap_warning_and_freshness_do_not_invent_a_required_observation():
    assert returns._returns_series_freshness() == "current"
    assert returns._returns_series_gap_tolerance_warnings(gaps=[SimpleNamespace(gap_days=1)], max_gap_days=1) == []
    assert returns._returns_series_gap_tolerance_warnings(gaps=[SimpleNamespace(gap_days=2)], max_gap_days=1)
