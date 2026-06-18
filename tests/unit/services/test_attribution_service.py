from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from app.models.attribution_requests import AttributionRequest
from app.services import attribution_service
from common.enums import PeriodType


def test_count_attribution_portfolio_rows_handles_absent_and_populated_sources():
    empty_request = SimpleNamespace(portfolio_data=None, instruments_data=None, portfolio_groups_data=None)
    populated_request = SimpleNamespace(
        portfolio_data=SimpleNamespace(valuation_points=[1, 2]),
        instruments_data=[SimpleNamespace(valuation_points=[1]), SimpleNamespace(valuation_points=[1, 2])],
        portfolio_groups_data=[SimpleNamespace(observations=[1, 2, 3])],
    )

    assert attribution_service._count_attribution_portfolio_rows(empty_request) == 0
    assert attribution_service._count_attribution_portfolio_rows(populated_request) == 8


def test_count_optional_nested_rows_handles_absent_and_populated_collections():
    assert attribution_service._count_optional_nested_rows(None, "observations") == 0
    assert (
        attribution_service._count_optional_nested_rows(
            [SimpleNamespace(observations=[1]), SimpleNamespace(observations=[1, 2])],
            "observations",
        )
        == 3
    )


def test_build_attribution_results_by_period_slices_non_empty_periods_and_prefixes_lineage(monkeypatch):
    effects_df = pd.DataFrame(
        {"effect": [0.1, 0.2]},
        index=pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp("2026-01-02"), "Equity"),
                (pd.Timestamp("2026-02-02"), "Fixed Income"),
            ],
            names=["date", "group"],
        ),
    )
    periods = [
        SimpleNamespace(name="JAN", start_date="2026-01-01", end_date="2026-01-31"),
        SimpleNamespace(name="MAR", start_date="2026-03-01", end_date="2026-03-31"),
    ]
    captured_slices: list[pd.DataFrame] = []

    def aggregate(period_slice_df, request):
        captured_slices.append(period_slice_df)
        return {"period_rows": len(period_slice_df), "portfolio_id": request.portfolio_id}, {
            "row_count": len(period_slice_df)
        }

    monkeypatch.setattr(attribution_service, "aggregate_attribution_results", aggregate)
    monkeypatch.setattr(
        attribution_service,
        "build_single_period_attribution_response",
        lambda period_result: {"wrapped": period_result},
    )

    lineage_data = {"engine": "complete"}
    request = SimpleNamespace(portfolio_id="DEMO_DPM_EUR_001")

    results = attribution_service._build_attribution_results_by_period(
        effects_df=effects_df,
        request=request,
        resolved_periods=periods,
        lineage_data=lineage_data,
    )

    assert list(results) == ["JAN"]
    assert results["JAN"] == {"wrapped": {"period_rows": 1, "portfolio_id": "DEMO_DPM_EUR_001"}}
    assert captured_slices[0].index.get_level_values("date").tolist() == [pd.Timestamp("2026-01-02")]
    assert lineage_data == {"engine": "complete", "JAN_row_count": 1}


def test_build_single_attribution_period_response_skips_empty_slices(monkeypatch):
    effects_df = pd.DataFrame(
        {"effect": [0.1]},
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), "Equity")],
            names=["date", "group"],
        ),
    )
    period = SimpleNamespace(name="FEB", start_date="2026-02-01", end_date="2026-02-28")
    lineage_data = {"engine": "complete"}

    def aggregate(*_args, **_kwargs):
        raise AssertionError("empty period slices must not be aggregated")

    monkeypatch.setattr(attribution_service, "aggregate_attribution_results", aggregate)

    response = attribution_service._build_single_attribution_period_response(
        effects_df,
        request=SimpleNamespace(portfolio_id="DEMO_DPM_EUR_001"),
        period=period,
        lineage_data=lineage_data,
    )

    assert response is None
    assert lineage_data == {"engine": "complete"}


def test_latest_attribution_observation_date_uses_all_stateless_input_sources():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_001",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-04-30",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["monthly"]}],
            "mode": "by_instrument",
            "group_by": ["assetClass"],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-31", "begin_mv": 1000.0, "end_mv": 1010.0}],
            },
            "instruments_data": [
                {
                    "instrument_id": "BOND_1",
                    "meta": {"assetClass": "Bond"},
                    "valuation_points": [{"perf_date": "2025-02-28", "begin_mv": 500.0, "end_mv": 505.0}],
                }
            ],
            "portfolio_groups_data": [
                {
                    "key": {"assetClass": "Equity"},
                    "observations": [{"date": "2025-03-31", "weight_bop": 1.0, "return_base": 0.01}],
                }
            ],
            "benchmark_groups_data": [
                {
                    "key": {"assetClass": "Equity"},
                    "observations": [{"date": "2025-04-30", "return_base": 0.02, "weight_bop": 1.0}],
                }
            ],
        }
    )

    assert attribution_service._portfolio_observation_dates(request) == [pd.Timestamp("2025-01-31").date()]
    assert attribution_service._instrument_observation_dates(request) == [pd.Timestamp("2025-02-28").date()]
    assert attribution_service._portfolio_group_observation_dates(request) == ["2025-03-31"]
    assert attribution_service._benchmark_group_observation_dates(request) == [pd.Timestamp("2025-04-30").date()]
    assert attribution_service._latest_attribution_observation_date(request) == pd.Timestamp("2025-04-30").date()


def test_portfolio_group_observation_helpers_filter_missing_dates():
    request = SimpleNamespace(
        portfolio_groups_data=[
            SimpleNamespace(
                observations=[
                    {"date": "2025-03-31", "weight_bop": 1.0},
                    {"date": "", "weight_bop": 1.0},
                    {"weight_bop": 1.0},
                ]
            )
        ]
    )

    observations = list(attribution_service._iter_portfolio_group_observations(request))

    assert len(observations) == 3
    assert attribution_service._portfolio_group_observation_date(observations[0]) == "2025-03-31"
    assert attribution_service._portfolio_group_observation_date(observations[1]) is None
    assert attribution_service._portfolio_group_observation_date(observations[2]) is None
    assert attribution_service._portfolio_group_observation_dates(request) == ["2025-03-31"]
    assert (
        list(attribution_service._iter_portfolio_group_observations(SimpleNamespace(portfolio_groups_data=None))) == []
    )


def test_resolve_attribution_execution_window_projects_master_request(monkeypatch):
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_001",
            "report_start_date": "2025-01-15",
            "report_end_date": "2025-03-31",
            "analyses": [
                {"period": "MTD", "frequencies": ["monthly"]},
                {"period": "QTD", "frequencies": ["monthly"]},
            ],
            "mode": "by_group",
            "group_by": ["assetClass"],
            "portfolio_groups_data": [
                {
                    "key": {"assetClass": "Equity"},
                    "observations": [{"date": "2025-03-31", "weight_bop": 1.0, "return_base": 0.01}],
                }
            ],
            "benchmark_groups_data": [
                {
                    "key": {"assetClass": "Equity"},
                    "observations": [{"date": "2025-03-31", "return_base": 0.02, "weight_bop": 1.0}],
                }
            ],
        }
    )
    resolved_periods = [
        SimpleNamespace(
            name="MTD", start_date=pd.Timestamp("2025-03-01").date(), end_date=pd.Timestamp("2025-03-31").date()
        ),
        SimpleNamespace(
            name="QTD", start_date=pd.Timestamp("2025-01-01").date(), end_date=pd.Timestamp("2025-03-31").date()
        ),
    ]
    captured: dict[str, object] = {}

    def resolve(periods_to_resolve, report_end_date, report_start_date, *, explicit_start_date):
        captured.update(
            {
                "periods_to_resolve": periods_to_resolve,
                "report_end_date": report_end_date,
                "report_start_date": report_start_date,
                "explicit_start_date": explicit_start_date,
            }
        )
        return resolved_periods

    monkeypatch.setattr(attribution_service, "resolve_periods", resolve)

    window = attribution_service._resolve_attribution_execution_window(request)

    assert window.periods_to_resolve == [PeriodType.MTD, PeriodType.QTD]
    assert window.resolved_periods is resolved_periods
    assert window.master_start_date == pd.Timestamp("2025-01-01").date()
    assert window.master_end_date == pd.Timestamp("2025-03-31").date()
    assert window.master_request is not request
    assert window.master_request.report_start_date == pd.Timestamp("2025-01-01").date()
    assert window.master_request.report_end_date == pd.Timestamp("2025-03-31").date()
    assert captured["periods_to_resolve"] == [PeriodType.MTD, PeriodType.QTD]
    assert captured["explicit_start_date"] == request.report_start_date


def test_resolve_attribution_execution_window_rejects_empty_resolved_periods(monkeypatch):
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_001",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["monthly"]}],
            "mode": "by_group",
            "group_by": ["assetClass"],
            "portfolio_groups_data": [],
            "benchmark_groups_data": [],
        }
    )
    monkeypatch.setattr(attribution_service, "resolve_periods", lambda *args, **kwargs: [])

    with pytest.raises(HTTPException) as exc_info:
        attribution_service._resolve_attribution_execution_window(request)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "No valid periods could be resolved."


def test_attribution_response_support_helpers_preserve_meta_supportability_and_benchmark_context(monkeypatch):
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_001",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["monthly"]}],
            "mode": "by_group",
            "group_by": ["assetClass"],
            "portfolio_groups_data": [
                {
                    "key": {"assetClass": "Equity"},
                    "observations": [{"date": "2025-01-31", "weight_bop": 1.0, "return_base": 0.01}],
                }
            ],
            "benchmark_groups_data": [
                {
                    "key": {"assetClass": "Equity"},
                    "observations": [{"date": "2025-01-31", "return_base": 0.02, "weight_bop": 1.0}],
                }
            ],
        }
    )
    recorded_metrics = []
    monkeypatch.setattr(
        attribution_service,
        "record_supportability_metric",
        lambda *, operation, supportability: recorded_metrics.append((operation, supportability)),
    )

    meta = attribution_service._build_attribution_meta(
        request=request,
        app_version="9.9.9-test",
        periods_to_resolve=[PeriodType.EXPLICIT],
        master_start_date=pd.Timestamp("2025-01-01").date(),
        master_end_date=pd.Timestamp("2025-01-31").date(),
        input_fingerprint="fingerprint-1",
        calculation_hash="hash-1",
    )
    supportability = attribution_service._build_attribution_supportability(request, resolved_period_count=1)

    assert meta.engine_version == "9.9.9-test"
    assert meta.periods == {
        "requested": ["EXPLICIT"],
        "master_start": "2025-01-01",
        "master_end": "2025-01-31",
    }
    assert meta.input_fingerprint == "fingerprint-1"
    assert meta.calculation_hash == "hash-1"
    assert supportability.input_row_count == 2
    assert supportability.resolved_period_count == 1
    assert supportability.freshness_bucket == "current"
    assert recorded_metrics == [("attribution", supportability)]
    assert attribution_service._attribution_benchmark_context(
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source="stateful_benchmark",
    ) == {"benchmark_id": "BMK_1", "return_source": "stateful_benchmark"}
    assert (
        attribution_service._attribution_benchmark_context(
            resolved_benchmark_id="BMK_1",
            resolved_benchmark_return_source=None,
        )
        is None
    )
