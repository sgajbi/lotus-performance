from types import SimpleNamespace

import pandas as pd

from engine.attribution_supportability import (
    _build_attribution_reason,
    _determine_attribution_supportability_status,
    _has_attribution_coverage_gap,
    build_attribution_supportability_evidence,
    classify_attribution_residual,
)


def _request():
    return SimpleNamespace(group_by=["sector"])


def test_attribution_supportability_status_prioritizes_coverage_gaps_over_warnings():
    coverage_reason = _build_attribution_reason("missing_benchmark_return", "warning", "Missing benchmark return.", 1)
    residual_warning = _build_attribution_reason("material_residual", "warning", "Material residual.", 0)

    assert _has_attribution_coverage_gap([coverage_reason]) is True
    assert _has_attribution_coverage_gap([residual_warning]) is False
    assert _determine_attribution_supportability_status([coverage_reason, residual_warning]) == "partial"
    assert _determine_attribution_supportability_status([residual_warning]) == "warning"
    assert _determine_attribution_supportability_status([]) == "valid"


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


def test_attribution_supportability_combines_alignment_reasons_and_lineage_flags_in_order():
    effects_df = pd.DataFrame(
        {
            "w_p": [0.4, 0.0, -0.2, 0.2],
            "w_b": [0.0, 0.3, 0.1, 0.2],
            "r_base_p": [0.01, 0.0, 0.02, 0.03],
            "r_base_b": [0.0, 0.02, 0.0, 0.0],
            "has_base_return_b": [True, True, False, True],
        },
        index=pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp("2025-01-01"), "Equity"),
                (pd.Timestamp("2025-01-01"), "Rates"),
                (pd.Timestamp("2025-01-01"), "Unknown"),
                (pd.Timestamp("2025-01-01"), "Credit"),
            ],
            names=["date", "sector"],
        ),
    )

    status, reason_codes, reasons, evidence, lineage = build_attribution_supportability_evidence(
        effects_df,
        _request(),
        currency_attribution_status="unavailable",
        linking_status="invalid_return_chain",
        residual_materiality=classify_attribution_residual(0.0),
    )

    assert status == "partial"
    assert reason_codes == [
        "off_benchmark_exposure",
        "benchmark_only_exposure",
        "unclassified_segment",
        "missing_benchmark_return",
        "negative_weight",
        "currency_attribution_unavailable",
        "linking_invalid_return_chain",
    ]
    assert [reason.severity for reason in reasons] == ["warning"] * 7
    assert evidence.portfolio_only_group_count == 1
    assert evidence.benchmark_only_group_count == 1
    assert evidence.unclassified_group_count == 1
    assert evidence.missing_benchmark_return_count == 1
    assert evidence.negative_weight_count == 1
    assert lineage["portfolio_only"].tolist() == [True, False, False, False]
    assert lineage["benchmark_only"].tolist() == [False, True, False, False]
    assert lineage["unclassified"].tolist() == [False, False, True, False]
    assert lineage["missing_benchmark_return"].tolist() == [False, False, True, False]
    assert lineage["negative_weight"].tolist() == [False, False, True, False]
