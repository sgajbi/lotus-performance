from __future__ import annotations

import pandas as pd

from app.models.attribution_requests import AttributionRequest
from app.models.attribution_responses import (
    AttributionReason,
    AttributionResidualMateriality,
    AttributionSupportabilityEvidence,
)

ATTRIBUTION_RESIDUAL_WARNING_THRESHOLD_PCT = 0.001
ATTRIBUTION_RESIDUAL_MATERIAL_THRESHOLD_PCT = 0.01


def classify_attribution_residual(residual: float) -> AttributionResidualMateriality:
    absolute_residual = abs(float(residual))
    if absolute_residual >= ATTRIBUTION_RESIDUAL_MATERIAL_THRESHOLD_PCT:
        classification = "material"
        treatment = "investigate"
    elif absolute_residual >= ATTRIBUTION_RESIDUAL_WARNING_THRESHOLD_PCT:
        classification = "watch"
        treatment = "review"
    else:
        classification = "immaterial"
        treatment = "no_action"
    return AttributionResidualMateriality(
        classification=classification,
        treatment=treatment,
        absolute_residual=absolute_residual,
        warning_threshold=ATTRIBUTION_RESIDUAL_WARNING_THRESHOLD_PCT,
        material_threshold=ATTRIBUTION_RESIDUAL_MATERIAL_THRESHOLD_PCT,
    )


def build_attribution_supportability_evidence(
    effects_df: pd.DataFrame,
    request: AttributionRequest,
    *,
    currency_attribution_status: str,
    linking_status: str,
    residual_materiality: AttributionResidualMateriality,
) -> tuple[str, list[str], list[AttributionReason], AttributionSupportabilityEvidence, pd.DataFrame]:
    effects_reset = effects_df.reset_index()
    if effects_reset.empty:
        reason = _build_attribution_reason(
            "missing_benchmark_data",
            "error",
            "No aligned portfolio and benchmark attribution observations were available for this period.",
            0,
        )
        return (
            "unavailable",
            [reason.code],
            [reason],
            AttributionSupportabilityEvidence(
                currency_attribution_status=currency_attribution_status,
                linking_status=linking_status,
            ),
            effects_reset,
        )

    group_by = request.group_by
    portfolio_only_mask = (effects_reset["w_p"] != 0) & (effects_reset["w_b"] == 0)
    benchmark_only_mask = (effects_reset["w_b"] != 0) & (effects_reset["w_p"] == 0)
    negative_weight_mask = (effects_reset["w_p"] < 0) | (effects_reset["w_b"] < 0)
    zero_exposure_mask = (effects_reset["w_p"] == 0) & (effects_reset["w_b"] == 0)
    if "has_base_return_b" in effects_reset.columns:
        missing_benchmark_return_mask = (effects_reset["w_b"] != 0) & (~effects_reset["has_base_return_b"].astype(bool))
    else:
        missing_benchmark_return_mask = (effects_reset["w_b"] != 0) & (effects_reset["r_base_b"] == 0)
    unclassified_mask = pd.Series(False, index=effects_reset.index)
    for group_col in group_by:
        unclassified_mask = (
            unclassified_mask
            | effects_reset[group_col].isna()
            | (effects_reset[group_col].astype(str).str.lower().isin({"", "unknown", "unclassified"}))
        )

    portfolio_only_count = _count_groups(portfolio_only_mask, effects_reset, group_by)
    benchmark_only_count = _count_groups(benchmark_only_mask, effects_reset, group_by)
    unclassified_count = _count_groups(unclassified_mask, effects_reset, group_by)
    missing_benchmark_return_count = _count_groups(missing_benchmark_return_mask, effects_reset, group_by)
    negative_weight_count = int(negative_weight_mask.sum())
    zero_exposure_count = int(zero_exposure_mask.sum())

    reasons: list[AttributionReason] = []
    if portfolio_only_count:
        reasons.append(
            _build_attribution_reason(
                "off_benchmark_exposure",
                "warning",
                "Portfolio contains exposure that is absent from the benchmark.",
                portfolio_only_count,
            )
        )
    if benchmark_only_count:
        reasons.append(
            _build_attribution_reason(
                "benchmark_only_exposure",
                "warning",
                "Benchmark contains exposure that is absent from the portfolio.",
                benchmark_only_count,
            )
        )
    if unclassified_count:
        reasons.append(
            _build_attribution_reason(
                "unclassified_segment",
                "warning",
                "One or more attribution groups resolved to the governed unclassified bucket.",
                unclassified_count,
            )
        )
    if missing_benchmark_return_count:
        reasons.append(
            _build_attribution_reason(
                "missing_benchmark_return",
                "warning",
                "Benchmark exposure was present but benchmark return evidence was missing.",
                missing_benchmark_return_count,
            )
        )
    if negative_weight_count:
        reasons.append(
            _build_attribution_reason(
                "negative_weight",
                "warning",
                "Negative portfolio or benchmark weights are present and preserved in attribution.",
                negative_weight_count,
            )
        )
    if zero_exposure_count:
        reasons.append(
            _build_attribution_reason(
                "zero_portfolio_exposure",
                "info",
                "Rows with no portfolio or benchmark exposure were retained as alignment evidence.",
                zero_exposure_count,
            )
        )
    if currency_attribution_status == "unavailable":
        reasons.append(
            _build_attribution_reason(
                "currency_attribution_unavailable",
                "warning",
                "Currency attribution was requested but required local or FX return evidence was unavailable.",
                0,
            )
        )
    if linking_status == "scaling_skipped":
        reasons.append(
            _build_attribution_reason(
                "linking_scaling_skipped",
                "warning",
                "Multi-period effect linking could not scale effects because arithmetic active return was zero.",
                0,
            )
        )
    if residual_materiality.classification == "material":
        reasons.append(
            _build_attribution_reason(
                "material_residual",
                "warning",
                "Attribution residual exceeded the governed materiality threshold.",
                0,
            )
        )
    elif residual_materiality.classification == "watch":
        reasons.append(
            _build_attribution_reason(
                "residual_watch",
                "info",
                "Attribution residual exceeded the review threshold but remained below the material threshold.",
                0,
            )
        )

    coverage_reason_codes = {
        "off_benchmark_exposure",
        "benchmark_only_exposure",
        "unclassified_segment",
        "missing_benchmark_return",
        "currency_attribution_unavailable",
    }
    reason_codes = [reason.code for reason in reasons]
    if any(code in coverage_reason_codes for code in reason_codes):
        status = "partial"
    elif any(reason.severity == "warning" for reason in reasons):
        status = "warning"
    else:
        status = "valid"

    evidence = AttributionSupportabilityEvidence(
        portfolio_only_group_count=portfolio_only_count,
        benchmark_only_group_count=benchmark_only_count,
        unclassified_group_count=unclassified_count,
        missing_benchmark_return_count=missing_benchmark_return_count,
        negative_weight_count=negative_weight_count,
        zero_portfolio_exposure_count=zero_exposure_count,
        currency_attribution_status=currency_attribution_status,
        linking_status=linking_status,
    )
    effects_reset["portfolio_only"] = portfolio_only_mask
    effects_reset["benchmark_only"] = benchmark_only_mask
    effects_reset["unclassified"] = unclassified_mask
    effects_reset["missing_benchmark_return"] = missing_benchmark_return_mask
    effects_reset["negative_weight"] = negative_weight_mask
    return status, reason_codes, reasons, evidence, effects_reset


def _count_groups(mask: pd.Series, df: pd.DataFrame, group_by: list[str]) -> int:
    if df.empty or not bool(mask.any()):
        return 0
    return int(df.loc[mask, group_by].drop_duplicates().shape[0])


def _build_attribution_reason(
    code: str,
    severity: str,
    message: str,
    affected_group_count: int,
) -> AttributionReason:
    return AttributionReason(
        code=code,
        severity=severity,
        message=message,
        affected_group_count=affected_group_count,
    )
