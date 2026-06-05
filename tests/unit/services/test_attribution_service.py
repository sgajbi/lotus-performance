from types import SimpleNamespace

import pandas as pd

from app.models.attribution_requests import AttributionRequest
from app.services import attribution_service
from common.enums import PeriodType


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
