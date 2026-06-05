from types import SimpleNamespace

import pandas as pd

from app.services import attribution_service


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
