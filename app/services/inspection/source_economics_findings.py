from __future__ import annotations

from app.models.inspection_responses import TWRInspectionFinding
from app.services.inspection.source_economics_collector import SourceEconomicsSamples


def build_source_economics_findings(
    *,
    portfolio_id: str,
    samples: SourceEconomicsSamples,
) -> list[TWRInspectionFinding]:
    findings: list[TWRInspectionFinding] = []

    if samples.invalid_observation_date_samples:
        findings.append(
            TWRInspectionFinding(
                code="INVALID_PORTFOLIO_OBSERVATION_DATE_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves observations without a usable valuation_date.",
                explanation=(
                    "The raw portfolio-timeseries payload includes one or more observation rows whose valuation_date "
                    "is missing or not a string. The inspector cannot align those rows to normalized TWR valuation "
                    "points, so it preserves the malformed observation identity as source-contract evidence."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries serialization and emit a YYYY-MM-DD valuation_date for "
                    "every portfolio observation row."
                ),
                evidence=_sample_evidence(
                    portfolio_id=portfolio_id,
                    samples=samples.invalid_observation_date_samples,
                ),
            )
        )

    findings.extend(_build_fee_source_economics_findings(portfolio_id=portfolio_id, samples=samples))
    findings.extend(_build_external_cashflow_findings(portfolio_id=portfolio_id, samples=samples))

    if samples.conflicting_explicit_amount_samples:
        findings.append(
            TWRInspectionFinding(
                code="CONFLICTING_EXPLICIT_SOURCE_TOTAL_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves conflicting explicit fee or cash-flow totals.",
                explanation=(
                    "The raw portfolio observation includes multiple explicit alias fields for the same source-total "
                    "semantic, but those numeric values disagree. The inspector resolves one value for downstream "
                    "comparison while preserving the contradiction as support evidence."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries alias fields and ensure equivalent explicit fee, bod "
                    "cash-flow, and eod cash-flow totals reconcile when multiple fields are served."
                ),
                evidence=_sample_evidence(
                    portfolio_id=portfolio_id,
                    samples=samples.conflicting_explicit_amount_samples,
                ),
            )
        )

    if samples.invalid_explicit_amount_samples:
        findings.append(
            TWRInspectionFinding(
                code="INVALID_EXPLICIT_SOURCE_AMOUNT_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves malformed explicit fee or cash-flow totals.",
                explanation=(
                    "The raw portfolio observation includes one or more explicit fee, bod cash-flow, or eod cash-flow "
                    "fields whose value cannot be parsed as a number. The inspector currently treats those fields as "
                    "unusable, so upstream source-economics lineage is incomplete until serialization is corrected."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries serialization and emit numeric values for explicit fee, "
                    "bod cash-flow, and eod cash-flow source fields when those fields are present."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.invalid_explicit_amount_samples),
            )
        )

    if samples.invalid_cashflow_collection_samples:
        findings.append(
            TWRInspectionFinding(
                code="INVALID_CASHFLOW_COLLECTION_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves a malformed cash_flows collection.",
                explanation=(
                    "The raw portfolio observation includes a cash_flows field, but the field is not a list of "
                    "detailed cash-flow rows. The inspector treats the malformed collection as unusable and "
                    "preserves it as source-contract evidence because detailed economics may have been lost."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries serialization and emit cash_flows as a list of "
                    "detailed cash-flow row objects when detailed cash-flow lineage is present."
                ),
                evidence=_sample_evidence(
                    portfolio_id=portfolio_id,
                    samples=samples.invalid_cashflow_collection_samples,
                ),
            )
        )

    if samples.invalid_cashflow_row_samples:
        findings.append(
            TWRInspectionFinding(
                code="INVALID_CASHFLOW_ROW_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves malformed detailed cash-flow rows.",
                explanation=(
                    "The raw portfolio observation includes a cash_flows list, but one or more entries are not "
                    "cash-flow row objects. The inspector skips those malformed entries for normalization and "
                    "preserves them as source-contract evidence."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries serialization and emit each cash_flows entry as a row "
                    "object with amount, timing, and cash_flow_type fields."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.invalid_cashflow_row_samples),
            )
        )

    if samples.invalid_amount_samples:
        findings.append(
            TWRInspectionFinding(
                code="INVALID_CASHFLOW_AMOUNT_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves detailed cash-flow rows with unusable amounts.",
                explanation=(
                    "The raw portfolio observation includes detailed cash-flow rows whose amount cannot be parsed as "
                    "a numeric value. The inspector cannot classify or reconcile those rows, so they represent lost "
                    "economic lineage until upstream serialization is corrected."
                ),
                recommended_action=(
                    "Review lotus-core detailed cash-flow serialization and emit a numeric amount for every "
                    "nonzero detailed cash-flow row."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.invalid_amount_samples),
            )
        )

    if samples.invalid_timing_samples:
        findings.append(
            TWRInspectionFinding(
                code="INVALID_CASHFLOW_TIMING_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves detailed cash-flow rows with unusable timing labels.",
                explanation=(
                    "The raw portfolio observation includes detailed cash-flow rows with missing, blank, or "
                    "unsupported timing values. The inspector only interprets canonical `bod` and `eod` timing "
                    "labels, so these rows need explicit upstream semantics."
                ),
                recommended_action=(
                    "Review lotus-core detailed cash-flow serialization and emit canonical `bod` or `eod` timing "
                    "labels for every nonzero detailed cash-flow row."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.invalid_timing_samples),
            )
        )

    if samples.missing_cashflow_type_samples:
        findings.append(
            TWRInspectionFinding(
                code="MISSING_CASHFLOW_TYPE_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves detailed cash-flow rows without a usable cash_flow_type label.",
                explanation=(
                    "The raw portfolio observation includes detailed cash-flow rows with no cash_flow_type label or "
                    "with a blank label. The inspector currently treats non-fee detailed rows as external economics, "
                    "so unlabeled rows need explicit upstream semantics or a governed mapping."
                ),
                recommended_action=(
                    "Review lotus-core detailed cash-flow serialization and emit canonical fee/external_flow "
                    "labels for every nonzero detailed cash-flow row."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.missing_cashflow_type_samples),
            )
        )

    if samples.noncanonical_cashflow_type_samples:
        findings.append(
            TWRInspectionFinding(
                code="NONCANONICAL_CASHFLOW_TYPE_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves non-canonical cash_flow_type values.",
                explanation=(
                    "The raw portfolio observation includes cash_flow_type labels outside the currently governed "
                    "inspection vocabulary. The inspector currently treats any non-fee detailed cash flow as external "
                    "economics, so unsupported labels need explicit source semantics or documented mapping."
                ),
                recommended_action=(
                    "Review lotus-core cash_flow_type vocabulary and either emit canonical fee/external_flow labels "
                    "or agree and document an explicit mapping for additional labels."
                ),
                evidence=_sample_evidence(
                    portfolio_id=portfolio_id,
                    samples=samples.noncanonical_cashflow_type_samples,
                ),
            )
        )

    if samples.governed_alias_cashflow_type_samples:
        findings.append(
            TWRInspectionFinding(
                code="GOVERNED_ALIAS_CASHFLOW_TYPE_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source uses cash_flow_type aliases that need explicit governance.",
                explanation=(
                    "The raw portfolio observation includes cash_flow_type labels that the inspector can map to "
                    "fee-like or external-flow economics, but those labels are not the canonical analytics-input "
                    "vocabulary. The inspector uses the mapped economic role for supportability checks while still "
                    "preserving the alias as contract evidence."
                ),
                recommended_action=(
                    "Review lotus-core cash_flow_type vocabulary and either emit canonical labels or publish the "
                    "alias mapping as a governed analytics-input contract."
                ),
                evidence=_sample_evidence(
                    portfolio_id=portfolio_id,
                    samples=samples.governed_alias_cashflow_type_samples,
                ),
            )
        )

    if samples.unsupported_cashflow_type_samples:
        findings.append(
            TWRInspectionFinding(
                code="UNSUPPORTED_CASHFLOW_TYPE_PRESENT",
                severity="warning",
                category="documentation_drift",
                owner_repo="lotus-core",
                summary="The stateful portfolio source uses cash_flow_type labels without supported TWR economics.",
                explanation=(
                    "The raw portfolio observation includes cash_flow_type labels that are not currently mapped to "
                    "fee or external-flow economics. The inspector preserves those rows as source-taxonomy evidence "
                    "and excludes them from fee/external normalization checks until the semantics are governed."
                ),
                recommended_action=(
                    "Review lotus-core cash_flow_type vocabulary and define whether each label should be modeled as "
                    "a fee, external flow, income/accrual item, tax item, or another explicit analytics-input role."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.unsupported_cashflow_type_samples),
            )
        )

    return findings


def _build_external_cashflow_findings(
    *,
    portfolio_id: str,
    samples: SourceEconomicsSamples,
) -> list[TWRInspectionFinding]:
    findings: list[TWRInspectionFinding] = []

    if samples.external_normalization_samples:
        findings.append(
            TWRInspectionFinding(
                code="EXTERNAL_CASHFLOW_NORMALIZATION_MISMATCH",
                severity="high",
                category="cashflow_classification",
                owner_repo="lotus-performance",
                summary="External source cash flows were not normalized into the served TWR valuation points accurately.",
                explanation=(
                    "The raw portfolio observation includes external-flow cash movements, but the normalized TWR "
                    "valuation points do not preserve those bod_cf or eod_cf amounts faithfully."
                ),
                recommended_action=(
                    "Review stateful portfolio normalization in lotus-performance so external cash flows tie exactly "
                    "from the raw portfolio source into the served valuation points."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.external_normalization_samples),
            )
        )

    if samples.duplicate_external_signal_samples:
        findings.append(
            TWRInspectionFinding(
                code="DUPLICATE_EXTERNAL_CASHFLOW_SOURCE_SIGNAL",
                severity="high",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source exposes duplicate external cash-flow signals for the same timing bucket.",
                explanation=(
                    "The raw portfolio observation carries both detailed external cash-flow rows and a separate "
                    "explicit bod/eod aggregate with the same magnitude, creating a duplication risk in downstream economics."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries cash-flow semantics and emit one authoritative external "
                    "cash-flow signal per timing bucket."
                ),
                evidence=_sample_evidence(
                    portfolio_id=portfolio_id,
                    samples=samples.duplicate_external_signal_samples,
                ),
            )
        )

    if samples.external_source_mismatch_samples:
        findings.append(
            TWRInspectionFinding(
                code="EXTERNAL_CASHFLOW_SOURCE_TOTAL_MISMATCH",
                severity="high",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves conflicting external cash-flow totals for the same timing bucket.",
                explanation=(
                    "The raw portfolio observation includes a bod/eod external cash-flow aggregate that does not tie "
                    "to the detailed external cash-flow rows for the same valuation date."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries cash-flow aggregation so explicit bod/eod totals and "
                    "detailed external cash-flow rows reconcile."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.external_source_mismatch_samples),
            )
        )

    if samples.external_timing_contradiction_samples:
        findings.append(
            TWRInspectionFinding(
                code="EXTERNAL_CASHFLOW_TIMING_BUCKET_CONTRADICTION",
                severity="high",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves external cash-flow totals in one timing bucket and detailed rows in the opposite bucket.",
                explanation=(
                    "The raw portfolio observation includes a bod or eod external cash-flow aggregate, but the "
                    "detailed external cash-flow rows for the same valuation date exist only in the opposite timing bucket."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries cash-flow timing semantics so explicit bod/eod totals "
                    "and detailed external cash-flow rows classify the movement in the same timing bucket."
                ),
                evidence=_sample_evidence(
                    portfolio_id=portfolio_id,
                    samples=samples.external_timing_contradiction_samples,
                ),
            )
        )

    if samples.external_mixed_timing_samples:
        findings.append(
            TWRInspectionFinding(
                code="EXTERNAL_CASHFLOW_MIXED_TIMING_BUCKETS",
                severity="warning",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves detailed external cash flows in both timing buckets for the same valuation date.",
                explanation=(
                    "The raw portfolio observation includes detailed external-flow rows in both beginning-of-day and "
                    "end-of-day buckets on the same valuation date. That can be legitimate, but it is timing-sensitive "
                    "for TWR support and should be visible as source-economics evidence."
                ),
                recommended_action=(
                    "Review the lotus-core transaction story for the sampled dates and confirm both external timing "
                    "buckets are intentional and reconcile to the normalized TWR valuation points."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.external_mixed_timing_samples),
            )
        )

    if samples.external_explicit_mixed_timing_samples:
        findings.append(
            TWRInspectionFinding(
                code="EXTERNAL_CASHFLOW_EXPLICIT_MIXED_TIMING_BUCKETS",
                severity="warning",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves explicit external cash-flow totals in both timing buckets for the same valuation date.",
                explanation=(
                    "The raw portfolio observation includes explicit beginning-of-day and end-of-day external "
                    "cash-flow totals on the same valuation date. That can be legitimate, but it is timing-sensitive "
                    "for TWR support even when no detailed rows are present, so the inspector preserves it as "
                    "source-economics evidence."
                ),
                recommended_action=(
                    "Review the lotus-core transaction story for the sampled dates and confirm both explicit external "
                    "timing buckets are intentional and reconcile to the normalized TWR valuation points."
                ),
                evidence=_sample_evidence(
                    portfolio_id=portfolio_id,
                    samples=samples.external_explicit_mixed_timing_samples,
                ),
            )
        )

    return findings


def _build_fee_source_economics_findings(
    *,
    portfolio_id: str,
    samples: SourceEconomicsSamples,
) -> list[TWRInspectionFinding]:
    findings: list[TWRInspectionFinding] = []

    if samples.fee_normalization_samples:
        findings.append(
            TWRInspectionFinding(
                code="FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED",
                severity="high",
                category="cashflow_classification",
                owner_repo="lotus-performance",
                summary="Fee source economics were not normalized faithfully into served mgmt_fees.",
                explanation=(
                    "The stateful portfolio source includes fee economics, but the normalized TWR valuation points "
                    "do not preserve those amounts accurately in mgmt_fees."
                ),
                recommended_action=(
                    "Preserve fee source economics during stateful portfolio normalization so served mgmt_fees tie "
                    "to the authoritative upstream fee signal."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.fee_normalization_samples),
            )
        )

    if samples.duplicate_fee_signal_samples:
        findings.append(
            TWRInspectionFinding(
                code="DUPLICATE_FEE_SOURCE_SIGNAL",
                severity="high",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source exposes duplicate fee signals for the same valuation date.",
                explanation=(
                    "The raw portfolio observation carries both fee-classified cash flows and a separate explicit fee "
                    "field with the same magnitude, creating a duplication risk in downstream economics."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries fee semantics and emit one authoritative fee signal per "
                    "valuation date."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.duplicate_fee_signal_samples),
            )
        )

    if samples.fee_source_mismatch_samples:
        findings.append(
            TWRInspectionFinding(
                code="FEE_SOURCE_TOTAL_MISMATCH",
                severity="high",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves conflicting fee totals for the same valuation date.",
                explanation=(
                    "The raw portfolio observation includes both fee-classified cash flows and an explicit fee total, "
                    "but those two source signals do not tie for the same valuation date."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries fee aggregation so explicit fee totals and detailed "
                    "fee-classified cash flows reconcile."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.fee_source_mismatch_samples),
            )
        )

    if samples.positive_fee_signal_samples:
        findings.append(
            TWRInspectionFinding(
                code="POSITIVE_FEE_SOURCE_SIGNAL",
                severity="high",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves a positive fee amount.",
                explanation=(
                    "Fee-classified source economics should reduce portfolio value. A positive fee amount is a strong "
                    "supportability signal that fee sign semantics are incorrect upstream."
                ),
                recommended_action=(
                    "Review lotus-core fee sign semantics and ensure fee-classified source amounts are emitted as "
                    "negative economics."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.positive_fee_signal_samples),
            )
        )

    if samples.fee_timing_bucket_samples:
        findings.append(
            TWRInspectionFinding(
                code="FEE_CASHFLOW_TIMING_BUCKET_UNSUPPORTED",
                severity="warning",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves fee-classified cash flows in the beginning-of-day bucket.",
                explanation=(
                    "Fee-classified source economics should be operational fee drag, not beginning-of-day capital "
                    "movement. The inspector still treats the amount as a fee for normalization checks, but preserves "
                    "the timing bucket as upstream contract evidence."
                ),
                recommended_action=(
                    "Review lotus-core portfolio-timeseries fee timing semantics and emit operational fee rows in "
                    "the canonical end-of-day timing bucket unless a separate governed fee timing model is approved."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.fee_timing_bucket_samples),
            )
        )

    if samples.fee_mixed_timing_samples:
        findings.append(
            TWRInspectionFinding(
                code="FEE_CASHFLOW_MIXED_TIMING_BUCKETS",
                severity="warning",
                category="cashflow_classification",
                owner_repo="lotus-core",
                summary="The stateful portfolio source serves fee-classified cash flows in both timing buckets for the same valuation date.",
                explanation=(
                    "The raw portfolio observation includes operational fee rows in both beginning-of-day and "
                    "end-of-day buckets on the same valuation date. Fees are normally fee drag rather than capital "
                    "movement, so mixed fee timing should be visible as upstream source-economics evidence."
                ),
                recommended_action=(
                    "Review the lotus-core fee transaction story for the sampled dates and emit one governed fee "
                    "timing model before relying on the result for production support triage."
                ),
                evidence=_sample_evidence(portfolio_id=portfolio_id, samples=samples.fee_mixed_timing_samples),
            )
        )

    return findings


def _sample_evidence(*, portfolio_id: str, samples: list[dict[str, object]]) -> dict[str, object]:
    return {
        "portfolio_id": portfolio_id,
        "sample_dates": [sample["valuation_date"] for sample in samples[:10]],
        "samples": samples[:10],
    }
