from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import pandas as pd

from engine.attribution_types import (
    AttributionReason,
    AttributionResidualMateriality,
    AttributionSupportabilityEvidence,
)

AttributionSupportabilityResult = tuple[
    str,
    list[str],
    list[AttributionReason],
    AttributionSupportabilityEvidence,
    pd.DataFrame,
]

ATTRIBUTION_RESIDUAL_WARNING_THRESHOLD_PCT = 0.001
ATTRIBUTION_RESIDUAL_MATERIAL_THRESHOLD_PCT = 0.01


class AttributionSupportabilityRequestLike(Protocol):
    @property
    def group_by(self) -> Sequence[str]: ...


@dataclass(frozen=True)
class _AttributionSupportabilityMasks:
    portfolio_only: pd.Series
    benchmark_only: pd.Series
    unclassified: pd.Series
    missing_benchmark_return: pd.Series
    negative_weight: pd.Series
    zero_exposure: pd.Series


@dataclass(frozen=True)
class _AttributionSupportabilityCounts:
    portfolio_only_group_count: int
    benchmark_only_group_count: int
    unclassified_group_count: int
    missing_benchmark_return_count: int
    negative_weight_count: int
    zero_portfolio_exposure_count: int


@dataclass(frozen=True)
class _AttributionSupportabilityProjection:
    status: str
    reason_codes: list[str]
    reasons: list[AttributionReason]
    evidence: AttributionSupportabilityEvidence
    lineage: pd.DataFrame

    def as_result(self) -> AttributionSupportabilityResult:
        return (
            self.status,
            self.reason_codes,
            self.reasons,
            self.evidence,
            self.lineage,
        )


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
    request: AttributionSupportabilityRequestLike,
    *,
    currency_attribution_status: str,
    linking_status: str,
    residual_materiality: AttributionResidualMateriality,
) -> AttributionSupportabilityResult:
    return _build_attribution_supportability_projection(
        effects_df=effects_df,
        request=request,
        currency_attribution_status=currency_attribution_status,
        linking_status=linking_status,
        residual_materiality=residual_materiality,
    ).as_result()


def _build_attribution_supportability_projection(
    *,
    effects_df: pd.DataFrame,
    request: AttributionSupportabilityRequestLike,
    currency_attribution_status: str,
    linking_status: str,
    residual_materiality: AttributionResidualMateriality,
) -> _AttributionSupportabilityProjection:
    effects_reset = effects_df.reset_index()
    if effects_reset.empty:
        return _build_empty_attribution_supportability_projection(
            effects_reset=effects_reset,
            currency_attribution_status=currency_attribution_status,
            linking_status=linking_status,
        )

    group_by = request.group_by
    masks = _build_attribution_supportability_masks(effects_reset, group_by)
    counts = _summarize_attribution_supportability_counts(
        masks=masks,
        effects_reset=effects_reset,
        group_by=group_by,
    )
    reasons = _build_attribution_supportability_reasons(
        counts=counts,
        currency_attribution_status=currency_attribution_status,
        linking_status=linking_status,
        residual_materiality=residual_materiality,
    )
    return _AttributionSupportabilityProjection(
        status=_determine_attribution_supportability_status(reasons),
        reason_codes=[reason.code for reason in reasons],
        reasons=reasons,
        evidence=_build_attribution_supportability_evidence(
            counts=counts,
            currency_attribution_status=currency_attribution_status,
            linking_status=linking_status,
        ),
        lineage=_append_attribution_supportability_lineage_flags(effects_reset, masks),
    )


def _build_empty_attribution_supportability_projection(
    *,
    effects_reset: pd.DataFrame,
    currency_attribution_status: str,
    linking_status: str,
) -> _AttributionSupportabilityProjection:
    reason = _build_attribution_reason(
        "missing_benchmark_data",
        "error",
        "No aligned portfolio and benchmark attribution observations were available for this period.",
        0,
    )
    return _AttributionSupportabilityProjection(
        status="unavailable",
        reason_codes=[reason.code],
        reasons=[reason],
        evidence=AttributionSupportabilityEvidence(
            currency_attribution_status=currency_attribution_status,
            linking_status=linking_status,
        ),
        lineage=effects_reset,
    )


def _build_attribution_supportability_evidence(
    *,
    counts: _AttributionSupportabilityCounts,
    currency_attribution_status: str,
    linking_status: str,
) -> AttributionSupportabilityEvidence:
    return AttributionSupportabilityEvidence(
        portfolio_only_group_count=counts.portfolio_only_group_count,
        benchmark_only_group_count=counts.benchmark_only_group_count,
        unclassified_group_count=counts.unclassified_group_count,
        missing_benchmark_return_count=counts.missing_benchmark_return_count,
        negative_weight_count=counts.negative_weight_count,
        zero_portfolio_exposure_count=counts.zero_portfolio_exposure_count,
        currency_attribution_status=currency_attribution_status,
        linking_status=linking_status,
    )


def _build_attribution_supportability_masks(
    effects_reset: pd.DataFrame,
    group_by: Sequence[str],
) -> _AttributionSupportabilityMasks:
    portfolio_only = (effects_reset["w_p"] != 0) & (effects_reset["w_b"] == 0)
    benchmark_only = (effects_reset["w_b"] != 0) & (effects_reset["w_p"] == 0)
    negative_weight = (effects_reset["w_p"] < 0) | (effects_reset["w_b"] < 0)
    zero_exposure = (effects_reset["w_p"] == 0) & (effects_reset["w_b"] == 0)
    if "has_base_return_b" in effects_reset.columns:
        missing_benchmark_return = (effects_reset["w_b"] != 0) & (~effects_reset["has_base_return_b"].astype(bool))
    else:
        missing_benchmark_return = (effects_reset["w_b"] != 0) & (effects_reset["r_base_b"] == 0)
    unclassified = _build_unclassified_group_mask(effects_reset, group_by)
    return _AttributionSupportabilityMasks(
        portfolio_only=portfolio_only,
        benchmark_only=benchmark_only,
        unclassified=unclassified,
        missing_benchmark_return=missing_benchmark_return,
        negative_weight=negative_weight,
        zero_exposure=zero_exposure,
    )


def _build_unclassified_group_mask(effects_reset: pd.DataFrame, group_by: Sequence[str]) -> pd.Series:
    unclassified = pd.Series(False, index=effects_reset.index)
    for group_col in group_by:
        unclassified = (
            unclassified
            | effects_reset[group_col].isna()
            | (effects_reset[group_col].astype(str).str.lower().isin({"", "unknown", "unclassified"}))
        )
    return unclassified


def _summarize_attribution_supportability_counts(
    *,
    masks: _AttributionSupportabilityMasks,
    effects_reset: pd.DataFrame,
    group_by: Sequence[str],
) -> _AttributionSupportabilityCounts:
    return _AttributionSupportabilityCounts(
        portfolio_only_group_count=_count_groups(masks.portfolio_only, effects_reset, group_by),
        benchmark_only_group_count=_count_groups(masks.benchmark_only, effects_reset, group_by),
        unclassified_group_count=_count_groups(masks.unclassified, effects_reset, group_by),
        missing_benchmark_return_count=_count_groups(masks.missing_benchmark_return, effects_reset, group_by),
        negative_weight_count=int(masks.negative_weight.sum()),
        zero_portfolio_exposure_count=int(masks.zero_exposure.sum()),
    )


def _build_attribution_supportability_reasons(
    *,
    counts: _AttributionSupportabilityCounts,
    currency_attribution_status: str,
    linking_status: str,
    residual_materiality: AttributionResidualMateriality,
) -> list[AttributionReason]:
    reasons: list[AttributionReason] = []
    _append_count_based_supportability_reasons(reasons, counts)
    _append_status_based_supportability_reasons(
        reasons,
        currency_attribution_status=currency_attribution_status,
        linking_status=linking_status,
        residual_materiality=residual_materiality,
    )
    return reasons


def _append_count_based_supportability_reasons(
    reasons: list[AttributionReason],
    counts: _AttributionSupportabilityCounts,
) -> None:
    _append_count_reason(
        reasons,
        count=counts.portfolio_only_group_count,
        code="off_benchmark_exposure",
        severity="warning",
        message="Portfolio contains exposure that is absent from the benchmark.",
    )
    _append_count_reason(
        reasons,
        count=counts.benchmark_only_group_count,
        code="benchmark_only_exposure",
        severity="warning",
        message="Benchmark contains exposure that is absent from the portfolio.",
    )
    _append_count_reason(
        reasons,
        count=counts.unclassified_group_count,
        code="unclassified_segment",
        severity="warning",
        message="One or more attribution groups resolved to the governed unclassified bucket.",
    )
    _append_count_reason(
        reasons,
        count=counts.missing_benchmark_return_count,
        code="missing_benchmark_return",
        severity="warning",
        message="Benchmark exposure was present but benchmark return evidence was missing.",
    )
    _append_count_reason(
        reasons,
        count=counts.negative_weight_count,
        code="negative_weight",
        severity="warning",
        message="Negative portfolio or benchmark weights are present and preserved in attribution.",
    )
    _append_count_reason(
        reasons,
        count=counts.zero_portfolio_exposure_count,
        code="zero_portfolio_exposure",
        severity="info",
        message="Rows with no portfolio or benchmark exposure were retained as alignment evidence.",
    )


def _append_status_based_supportability_reasons(
    reasons: list[AttributionReason],
    *,
    currency_attribution_status: str,
    linking_status: str,
    residual_materiality: AttributionResidualMateriality,
) -> None:
    _append_status_reason(
        reasons,
        actual_status=currency_attribution_status,
        expected_status="unavailable",
        code="currency_attribution_unavailable",
        message="Currency attribution was requested but required currency grouping or local/FX return evidence was unavailable.",
    )
    _append_status_reason(
        reasons,
        actual_status=linking_status,
        expected_status="scaling_skipped",
        code="linking_scaling_skipped",
        message="Multi-period effect linking could not scale effects because arithmetic active return was zero.",
    )
    _append_status_reason(
        reasons,
        actual_status=linking_status,
        expected_status="invalid_return_chain",
        code="linking_invalid_return_chain",
        message="Multi-period linking was requested but one or more portfolio or benchmark period returns were less than or equal to -100%.",
    )
    _append_residual_materiality_reason(reasons, residual_materiality)


def _append_count_reason(
    reasons: list[AttributionReason],
    *,
    count: int,
    code: str,
    severity: str,
    message: str,
) -> None:
    if count:
        reasons.append(_build_attribution_reason(code, severity, message, count))


def _append_status_reason(
    reasons: list[AttributionReason],
    *,
    actual_status: str,
    expected_status: str,
    code: str,
    message: str,
) -> None:
    if actual_status == expected_status:
        reasons.append(_build_attribution_reason(code, "warning", message, 0))


def _append_residual_materiality_reason(
    reasons: list[AttributionReason],
    residual_materiality: AttributionResidualMateriality,
) -> None:
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


def _determine_attribution_supportability_status(reasons: Sequence[AttributionReason]) -> str:
    if _has_attribution_coverage_gap(reasons):
        return "partial"
    if any(reason.severity == "warning" for reason in reasons):
        return "warning"
    return "valid"


def _has_attribution_coverage_gap(reasons: Sequence[AttributionReason]) -> bool:
    coverage_reason_codes = {
        "off_benchmark_exposure",
        "benchmark_only_exposure",
        "unclassified_segment",
        "missing_benchmark_return",
        "currency_attribution_unavailable",
        "linking_invalid_return_chain",
    }
    reason_codes = [reason.code for reason in reasons]
    return any(code in coverage_reason_codes for code in reason_codes)


def _append_attribution_supportability_lineage_flags(
    effects_reset: pd.DataFrame,
    masks: _AttributionSupportabilityMasks,
) -> pd.DataFrame:
    effects_reset["portfolio_only"] = masks.portfolio_only
    effects_reset["benchmark_only"] = masks.benchmark_only
    effects_reset["unclassified"] = masks.unclassified
    effects_reset["missing_benchmark_return"] = masks.missing_benchmark_return
    effects_reset["negative_weight"] = masks.negative_weight
    return effects_reset


def _count_groups(mask: pd.Series, df: pd.DataFrame, group_by: Sequence[str]) -> int:
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
