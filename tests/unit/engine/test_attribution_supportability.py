from types import SimpleNamespace

import pandas as pd

from engine.attribution_supportability import (
    build_attribution_supportability_evidence,
    classify_attribution_residual,
)


def _request():
    return SimpleNamespace(group_by=["sector"])


def test_attribution_supportability_handles_empty_evidence_as_unavailable():
    status, reason_codes, reasons, evidence, lineage = build_attribution_supportability_evidence(
        pd.DataFrame(),
        _request(),
        currency_attribution_status="not_requested",
        linking_status="not_requested",
        residual_materiality=classify_attribution_residual(0.0),
    )

    assert status == "unavailable"
    assert reason_codes == ["missing_benchmark_data"]
    assert reasons[0].severity == "error"
    assert evidence.currency_attribution_status == "not_requested"
    assert lineage.empty


def test_attribution_supportability_falls_back_when_return_presence_flag_is_absent():
    effects_df = pd.DataFrame(
        {
            "w_p": [0.5],
            "w_b": [0.5],
            "r_base_p": [0.01],
            "r_base_b": [0.0],
        },
        index=pd.MultiIndex.from_tuples([(pd.Timestamp("2025-01-01"), "Health")], names=["date", "sector"]),
    )

    status, reason_codes, _, evidence, lineage = build_attribution_supportability_evidence(
        effects_df,
        _request(),
        currency_attribution_status="not_requested",
        linking_status="not_requested",
        residual_materiality=classify_attribution_residual(0.0),
    )

    assert status == "partial"
    assert reason_codes == ["missing_benchmark_return"]
    assert evidence.missing_benchmark_return_count == 1
    assert lineage["missing_benchmark_return"].tolist() == [True]


def test_attribution_supportability_reports_zero_exposure_and_residual_watch_without_degrading_status():
    effects_df = pd.DataFrame(
        {
            "w_p": [0.0],
            "w_b": [0.0],
            "r_base_p": [0.0],
            "r_base_b": [0.0],
            "has_base_return_b": [True],
        },
        index=pd.MultiIndex.from_tuples([(pd.Timestamp("2025-01-01"), "Cash")], names=["date", "sector"]),
    )

    status, reason_codes, reasons, evidence, _ = build_attribution_supportability_evidence(
        effects_df,
        _request(),
        currency_attribution_status="not_requested",
        linking_status="not_requested",
        residual_materiality=classify_attribution_residual(0.005),
    )

    assert status == "valid"
    assert reason_codes == ["zero_portfolio_exposure", "residual_watch"]
    assert [reason.severity for reason in reasons] == ["info", "info"]
    assert evidence.zero_portfolio_exposure_count == 1


def test_attribution_supportability_warns_for_material_residual_without_coverage_gap():
    effects_df = pd.DataFrame(
        {
            "w_p": [0.5],
            "w_b": [0.5],
            "r_base_p": [0.02],
            "r_base_b": [0.01],
            "has_base_return_b": [True],
        },
        index=pd.MultiIndex.from_tuples([(pd.Timestamp("2025-01-01"), "Technology")], names=["date", "sector"]),
    )

    status, reason_codes, reasons, _, _ = build_attribution_supportability_evidence(
        effects_df,
        _request(),
        currency_attribution_status="not_requested",
        linking_status="not_requested",
        residual_materiality=classify_attribution_residual(0.02),
    )

    assert status == "warning"
    assert reason_codes == ["material_residual"]
    assert reasons[0].severity == "warning"
