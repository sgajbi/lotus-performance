from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.inspection_responses import TWRInspectionFinding

_RECONCILIATION_SAMPLE_LIMIT = 25


def _decimal_to_artifact(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True)
class ReconciliationCheckResult:
    findings: list[TWRInspectionFinding]
    evidence_summary: dict[str, object]
    artifact_payload: dict[str, object]


@dataclass(frozen=True)
class PositionReconciliationEvidenceInputs:
    portfolio_id: str
    findings: list[TWRInspectionFinding]
    overlapping_dates: list[str]
    position_rows: list[dict[str, object]]
    selected_position_rows: list[dict[str, object]]
    mixed_epoch_dates: list[str]
    duplicate_snapshot_samples: list[dict[str, object]]
    invalid_epoch_samples: list[dict[str, object]]
    invalid_position_value_samples: list[dict[str, object]]
    gap_details: list[dict[str, object]]
    max_abs_gap_amount: Decimal
    position_continuity_gap_samples: list[dict[str, object]]


@dataclass(frozen=True)
class _PositionReconciliationEvidenceCounts:
    duplicate_snapshot_dates: set[object]
    invalid_position_epoch_dates: set[object]
    invalid_position_value_dates: set[object]


def build_position_reconciliation_result(
    evidence: PositionReconciliationEvidenceInputs,
) -> ReconciliationCheckResult:
    counts = _position_reconciliation_evidence_counts(evidence)
    return ReconciliationCheckResult(
        findings=evidence.findings,
        evidence_summary=_position_reconciliation_evidence_summary(evidence, counts),
        artifact_payload=_position_reconciliation_artifact_payload(evidence, counts),
    )


def _position_reconciliation_evidence_counts(
    evidence: PositionReconciliationEvidenceInputs,
) -> _PositionReconciliationEvidenceCounts:
    return _PositionReconciliationEvidenceCounts(
        duplicate_snapshot_dates={sample["valuation_date"] for sample in evidence.duplicate_snapshot_samples},
        invalid_position_epoch_dates={sample["valuation_date"] for sample in evidence.invalid_epoch_samples},
        invalid_position_value_dates={sample["valuation_date"] for sample in evidence.invalid_position_value_samples},
    )


def _position_reconciliation_evidence_summary(
    evidence: PositionReconciliationEvidenceInputs,
    counts: _PositionReconciliationEvidenceCounts,
) -> dict[str, object]:
    return {
        "reconciliation_dates_checked": len(evidence.overlapping_dates),
        "position_row_count": len(evidence.position_rows),
        "selected_position_row_count": len(evidence.selected_position_rows),
        "mixed_epoch_date_count": len(evidence.mixed_epoch_dates),
        "duplicate_snapshot_date_count": len(counts.duplicate_snapshot_dates),
        "duplicate_snapshot_row_count": len(evidence.duplicate_snapshot_samples),
        "invalid_position_epoch_date_count": len(counts.invalid_position_epoch_dates),
        "invalid_position_epoch_row_count": len(evidence.invalid_epoch_samples),
        "invalid_position_value_date_count": len(counts.invalid_position_value_dates),
        "invalid_position_value_row_count": len(evidence.invalid_position_value_samples),
        "reconciliation_gap_date_count": len(evidence.gap_details),
        "reconciliation_max_gap_amount": _decimal_to_artifact(evidence.max_abs_gap_amount),
        "position_continuity_gap_count": len(evidence.position_continuity_gap_samples),
    }


def _position_reconciliation_artifact_payload(
    evidence: PositionReconciliationEvidenceInputs,
    counts: _PositionReconciliationEvidenceCounts,
) -> dict[str, object]:
    return {
        "portfolio_id": evidence.portfolio_id,
        "reconciliation_dates_checked": len(evidence.overlapping_dates),
        "position_row_count": len(evidence.position_rows),
        "selected_position_row_count": len(evidence.selected_position_rows),
        "mixed_epoch_dates": evidence.mixed_epoch_dates,
        "mixed_epoch_date_count": len(evidence.mixed_epoch_dates),
        "duplicate_snapshot_date_count": len(counts.duplicate_snapshot_dates),
        "duplicate_snapshot_row_count": len(evidence.duplicate_snapshot_samples),
        "duplicate_snapshot_samples": evidence.duplicate_snapshot_samples[:_RECONCILIATION_SAMPLE_LIMIT],
        "invalid_position_epoch_date_count": len(counts.invalid_position_epoch_dates),
        "invalid_position_epoch_row_count": len(evidence.invalid_epoch_samples),
        "invalid_position_epoch_samples": evidence.invalid_epoch_samples[:_RECONCILIATION_SAMPLE_LIMIT],
        "invalid_position_value_date_count": len(counts.invalid_position_value_dates),
        "invalid_position_value_row_count": len(evidence.invalid_position_value_samples),
        "invalid_position_value_samples": evidence.invalid_position_value_samples[:_RECONCILIATION_SAMPLE_LIMIT],
        "reconciliation_gap_date_count": len(evidence.gap_details),
        "max_gap_amount": _decimal_to_artifact(evidence.max_abs_gap_amount),
        "gap_samples": evidence.gap_details[:_RECONCILIATION_SAMPLE_LIMIT],
        "position_continuity_gap_count": len(evidence.position_continuity_gap_samples),
        "position_continuity_gap_samples": evidence.position_continuity_gap_samples[:_RECONCILIATION_SAMPLE_LIMIT],
    }
