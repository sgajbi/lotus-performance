from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.config import Settings, get_settings
from app.models.inspection_requests import TWRInspectionProfile
from app.models.inspection_responses import TWRInspectionFinding
from app.models.requests import PerformanceRequest
from app.services.inspection.source_availability import raise_inspection_source_unavailable
from app.services.portfolio_source_service import build_stateful_input_service

_ABSOLUTE_GAP_TOLERANCE = Decimal("0.01")
_RELATIVE_GAP_TOLERANCE = Decimal("0.0001")
_TRANSITION_ACTIVITY_FIELD_TOKENS = ("cashflow", "cash_flow", "trade", "quantity_delta")
_INSPECTOR_CONSUMER_SYSTEM = "lotus-performance-inspector"
_FINDING_SAMPLE_LIMIT = 10
_RECONCILIATION_SAMPLE_LIMIT = 25
_PositionRowSelection = dict[tuple[str, str], tuple[int, dict[str, object]]]
_PositionContinuityPair = tuple[str, dict[str, object], dict[str, object]]
_DuplicateSnapshotKey = tuple[str, str, int]


def _decimal_to_artifact(value: Decimal) -> str:
    return format(value, "f")


def _decimal_pct_to_float(pct: Decimal) -> float:
    return float(pct)  # monetary-float-allow


def _sampled_position_finding_evidence(
    samples: list[dict[str, object]],
    *,
    date_key: str,
    count_key: str,
    samples_key: str,
) -> dict[str, object]:
    sampled_rows = samples[:_FINDING_SAMPLE_LIMIT]
    return {
        date_key: [sample["valuation_date"] for sample in sampled_rows],
        count_key: len(samples),
        samples_key: sampled_rows,
    }


def _position_sample_finding(
    *,
    portfolio_id: str,
    samples: list[dict[str, object]],
    spec: _PositionSampleFindingSpec,
) -> TWRInspectionFinding:
    return TWRInspectionFinding(
        code=spec.code,
        severity=spec.severity,
        category=spec.category,
        owner_repo="lotus-core",
        summary=spec.summary,
        explanation=spec.explanation,
        recommended_action=spec.recommended_action,
        evidence={
            "portfolio_id": portfolio_id,
            **_sampled_position_finding_evidence(
                samples,
                date_key=spec.date_key,
                count_key=spec.count_key,
                samples_key=spec.samples_key,
            ),
        },
    )


@dataclass(frozen=True)
class _PositionSampleFindingSpec:
    code: str
    severity: str
    category: str
    summary: str
    explanation: str
    recommended_action: str
    date_key: str
    count_key: str
    samples_key: str


@dataclass(frozen=True)
class ReconciliationCheckResult:
    findings: list[TWRInspectionFinding]
    evidence_summary: dict[str, object]
    artifact_payload: dict[str, object]


@dataclass(frozen=True)
class _PositionReconciliationGapAnalysis:
    overlapping_dates: list[str]
    gap_details: list[dict[str, object]]
    max_abs_gap_amount: Decimal


@dataclass(frozen=True)
class _PositionContinuityValues:
    previous_end_field: str
    previous_end: Decimal
    current_begin_field: str
    current_begin: Decimal


@dataclass(frozen=True)
class _PositionContinuityGap:
    values: _PositionContinuityValues
    gap_amount: Decimal
    gap_pct_of_previous_end: float | None


@dataclass
class _DuplicateSnapshotSamples:
    counts: dict[_DuplicateSnapshotKey, int]
    sample_index_by_key: dict[_DuplicateSnapshotKey, int]
    samples: list[dict[str, object]]


_DUPLICATE_POSITION_SNAPSHOT_FINDING = _PositionSampleFindingSpec(
    code="DUPLICATE_POSITION_SNAPSHOT_ROW_PRESENT",
    severity="warning",
    category="epoch_coherence",
    summary="Position timeseries includes duplicate rows for the same position snapshot.",
    explanation=(
        "The served position source includes multiple rows with the same valuation date, position id, "
        "and snapshot epoch. The inspector collapses those duplicates during latest-row selection, so "
        "upstream snapshot publication is not uniquely identifying a promoted position state."
    ),
    recommended_action=(
        "Review lotus-core position-timeseries publication and ensure each position/date/epoch snapshot "
        "is emitted once."
    ),
    date_key="duplicate_snapshot_dates",
    count_key="duplicate_snapshot_row_count",
    samples_key="duplicate_snapshot_samples",
)
_INVALID_POSITION_EPOCH_FINDING = _PositionSampleFindingSpec(
    code="INVALID_POSITION_EPOCH_PRESENT",
    severity="warning",
    category="epoch_coherence",
    summary="Position timeseries includes rows with unusable snapshot epoch values.",
    explanation=(
        "One or more served position rows carry a non-numeric epoch label. The inspector falls back to epoch `0` "
        "for those rows, so upstream epoch serialization is not explicit enough to support a trustworthy "
        "latest-snapshot selection."
    ),
    recommended_action=(
        "Review lotus-core position snapshot serialization and emit numeric valuation epochs for every served "
        "position row."
    ),
    date_key="invalid_position_epoch_dates",
    count_key="invalid_position_epoch_row_count",
    samples_key="invalid_position_epoch_samples",
)
_INVALID_POSITION_VALUE_FINDING = _PositionSampleFindingSpec(
    code="INVALID_POSITION_END_VALUE_PRESENT",
    severity="warning",
    category="portfolio_position_reconciliation",
    summary="Latest position-state rows include unusable ending market values.",
    explanation=(
        "After selecting the latest position row per valuation date and position, one or more rows still carry "
        "missing, blank, or non-numeric ending market values. The inspector excludes those rows from "
        "reconciliation totals, so upstream position-state serialization is incomplete."
    ),
    recommended_action=(
        "Review lotus-core position-timeseries serialization and emit numeric ending market values for every "
        "promoted position row."
    ),
    date_key="invalid_position_value_dates",
    count_key="invalid_position_value_row_count",
    samples_key="invalid_position_value_samples",
)
_POSITION_CONTINUITY_GAP_FINDING = _PositionSampleFindingSpec(
    code="POSITION_BEGIN_VALUE_CARRY_FORWARD_BREAK",
    severity="high",
    category="portfolio_position_reconciliation",
    summary="Position timeseries has unexplained begin-value carry-forward breaks.",
    explanation=(
        "For one or more positions, the current beginning market value does not carry forward from the prior "
        "selected ending market value, and the current source row does not include explanatory cash-flow or "
        "trade activity. This is the source-state pattern that can produce implausible daily TWR moves even "
        "when portfolio and position end totals reconcile."
    ),
    recommended_action=(
        "Review lotus-core position-timeseries assembly for the sampled positions and ensure beginning market "
        "values are derived from the prior promoted ending state unless a governed activity row explains the "
        "transition."
    ),
    date_key="continuity_gap_dates",
    count_key="position_continuity_gap_count",
    samples_key="position_continuity_gap_samples",
)


def run_reconciliation_checks(
    *,
    performance_request: PerformanceRequest,
    portfolio_id: str,
    inspection_profile: TWRInspectionProfile,
    settings: Settings | None = None,
) -> ReconciliationCheckResult:
    position_payload = asyncio.run(
        _fetch_position_timeseries(
            performance_request=performance_request,
            portfolio_id=portfolio_id,
            settings=settings or get_settings(),
        )
    )
    return analyze_portfolio_position_reconciliation(
        performance_request=performance_request,
        portfolio_id=portfolio_id,
        inspection_profile=inspection_profile,
        position_rows=_position_rows_from_payload(position_payload),
    )


async def _fetch_position_timeseries(
    *,
    performance_request: PerformanceRequest,
    portfolio_id: str,
    settings: Settings,
) -> dict[str, object]:
    stateful_input_service = build_stateful_input_service(settings=settings)
    status_code, payload = await stateful_input_service.get_position_timeseries(
        portfolio_id=portfolio_id,
        as_of_date=performance_request.report_end_date,
        start_date=performance_request.performance_start_date,
        end_date=performance_request.report_end_date,
        reporting_currency=performance_request.report_ccy,
        consumer_system=_INSPECTOR_CONSUMER_SYSTEM,
        calculation_id=None,
    )
    if status_code >= 400:
        raise_inspection_source_unavailable(
            source_label="Position timeseries",
            inspection_label="reconciliation",
            status_code=status_code,
        )
    return payload


def analyze_portfolio_position_reconciliation(
    *,
    performance_request: PerformanceRequest,
    portfolio_id: str,
    inspection_profile: TWRInspectionProfile,
    position_rows: list[dict[str, object]],
) -> ReconciliationCheckResult:
    del inspection_profile

    portfolio_end_by_date = {
        point.perf_date.isoformat(): Decimal(str(point.end_mv)) for point in performance_request.valuation_points
    }
    duplicate_snapshot_samples = _collect_duplicate_snapshot_samples(position_rows)
    invalid_epoch_samples = _collect_invalid_epoch_samples(position_rows)
    selected_position_rows = _select_latest_position_rows(position_rows)
    position_end_by_date, invalid_position_value_samples = _sum_position_end_values_by_date(selected_position_rows)
    position_continuity_gap_samples = _collect_position_continuity_gap_samples(selected_position_rows)

    mixed_epoch_dates = sorted(_find_mixed_epoch_dates(position_rows))

    gap_analysis = _analyze_position_reconciliation_gaps(
        portfolio_end_by_date=portfolio_end_by_date,
        position_end_by_date=position_end_by_date,
    )
    overlapping_dates = gap_analysis.overlapping_dates
    gap_details = gap_analysis.gap_details
    max_abs_gap_amount = gap_analysis.max_abs_gap_amount
    findings = _build_position_reconciliation_findings(
        portfolio_id=portfolio_id,
        mixed_epoch_dates=mixed_epoch_dates,
        duplicate_snapshot_samples=duplicate_snapshot_samples,
        invalid_epoch_samples=invalid_epoch_samples,
        invalid_position_value_samples=invalid_position_value_samples,
        gap_details=gap_details,
        max_abs_gap_amount=max_abs_gap_amount,
        position_continuity_gap_samples=position_continuity_gap_samples,
    )
    return _build_position_reconciliation_result(
        portfolio_id=portfolio_id,
        findings=findings,
        overlapping_dates=overlapping_dates,
        position_rows=position_rows,
        selected_position_rows=selected_position_rows,
        mixed_epoch_dates=mixed_epoch_dates,
        duplicate_snapshot_samples=duplicate_snapshot_samples,
        invalid_epoch_samples=invalid_epoch_samples,
        invalid_position_value_samples=invalid_position_value_samples,
        gap_details=gap_details,
        max_abs_gap_amount=max_abs_gap_amount,
        position_continuity_gap_samples=position_continuity_gap_samples,
    )


def _build_position_reconciliation_findings(
    *,
    portfolio_id: str,
    mixed_epoch_dates: list[str],
    duplicate_snapshot_samples: list[dict[str, object]],
    invalid_epoch_samples: list[dict[str, object]],
    invalid_position_value_samples: list[dict[str, object]],
    gap_details: list[dict[str, object]],
    max_abs_gap_amount: Decimal,
    position_continuity_gap_samples: list[dict[str, object]],
) -> list[TWRInspectionFinding]:
    findings: list[TWRInspectionFinding] = []
    _append_reconciliation_finding_when_present(
        findings,
        mixed_epoch_dates,
        lambda: _mixed_position_epoch_finding(portfolio_id, mixed_epoch_dates),
    )
    _append_reconciliation_finding_when_present(
        findings,
        duplicate_snapshot_samples,
        lambda: _duplicate_position_snapshot_finding(portfolio_id, duplicate_snapshot_samples),
    )
    _append_reconciliation_finding_when_present(
        findings,
        invalid_epoch_samples,
        lambda: _invalid_position_epoch_finding(portfolio_id, invalid_epoch_samples),
    )
    _append_reconciliation_finding_when_present(
        findings,
        invalid_position_value_samples,
        lambda: _invalid_position_value_finding(portfolio_id, invalid_position_value_samples),
    )
    _append_reconciliation_finding_when_present(
        findings,
        gap_details,
        lambda: _position_reconciliation_gap_finding(portfolio_id, gap_details, max_abs_gap_amount),
    )
    _append_reconciliation_finding_when_present(
        findings,
        position_continuity_gap_samples,
        lambda: _position_continuity_gap_finding(portfolio_id, position_continuity_gap_samples),
    )
    return findings


def _append_reconciliation_finding_when_present(
    findings: list[TWRInspectionFinding],
    evidence_items: Collection[object],
    finding_factory: Callable[[], TWRInspectionFinding],
) -> None:
    if evidence_items:
        findings.append(finding_factory())


def _mixed_position_epoch_finding(portfolio_id: str, mixed_epoch_dates: list[str]) -> TWRInspectionFinding:
    return TWRInspectionFinding(
        code="MIXED_POSITION_EPOCH_SNAPSHOT",
        severity="high",
        category="epoch_coherence",
        owner_repo="lotus-core",
        summary="Position timeseries contains mixed snapshot epochs for the same valuation date.",
        explanation=(
            "A coherent portfolio-state reconciliation requires one promoted snapshot state per valuation date. "
            "The served position rows include multiple epochs on the same date."
        ),
        recommended_action=(
            "Review lotus-core position snapshot promotion and ensure one coherent epoch is served per portfolio date."
        ),
        evidence={
            "portfolio_id": portfolio_id,
            "mixed_epoch_dates": mixed_epoch_dates[:10],
            "mixed_epoch_date_count": len(mixed_epoch_dates),
        },
    )


def _duplicate_position_snapshot_finding(
    portfolio_id: str,
    duplicate_snapshot_samples: list[dict[str, object]],
) -> TWRInspectionFinding:
    return _position_sample_finding(
        portfolio_id=portfolio_id,
        samples=duplicate_snapshot_samples,
        spec=_DUPLICATE_POSITION_SNAPSHOT_FINDING,
    )


def _invalid_position_epoch_finding(
    portfolio_id: str,
    invalid_epoch_samples: list[dict[str, object]],
) -> TWRInspectionFinding:
    return _position_sample_finding(
        portfolio_id=portfolio_id,
        samples=invalid_epoch_samples,
        spec=_INVALID_POSITION_EPOCH_FINDING,
    )


def _invalid_position_value_finding(
    portfolio_id: str,
    invalid_position_value_samples: list[dict[str, object]],
) -> TWRInspectionFinding:
    return _position_sample_finding(
        portfolio_id=portfolio_id,
        samples=invalid_position_value_samples,
        spec=_INVALID_POSITION_VALUE_FINDING,
    )


def _position_reconciliation_gap_finding(
    portfolio_id: str,
    gap_details: list[dict[str, object]],
    max_abs_gap_amount: Decimal,
) -> TWRInspectionFinding:
    return TWRInspectionFinding(
        code="PORTFOLIO_POSITION_RECONCILIATION_GAP",
        severity="high",
        category="portfolio_position_reconciliation",
        owner_repo="lotus-core",
        summary="Portfolio totals do not reconcile to the latest coherent position state.",
        explanation=(
            "The served portfolio ending market value differs from the latest position-state total on one or more "
            "inspected dates beyond the governed reconciliation tolerance."
        ),
        recommended_action=(
            "Review lotus-core aggregate portfolio valuation assembly, position snapshot promotion, and source-state "
            "reconciliation controls."
        ),
        evidence={
            "portfolio_id": portfolio_id,
            "reconciliation_gap_dates": [detail["valuation_date"] for detail in gap_details[:10]],
            "gap_samples": gap_details[:10],
            "max_gap_amount": _decimal_to_artifact(max_abs_gap_amount),
        },
    )


def _position_continuity_gap_finding(
    portfolio_id: str,
    position_continuity_gap_samples: list[dict[str, object]],
) -> TWRInspectionFinding:
    return _position_sample_finding(
        portfolio_id=portfolio_id,
        samples=position_continuity_gap_samples,
        spec=_POSITION_CONTINUITY_GAP_FINDING,
    )


def _build_position_reconciliation_result(
    *,
    portfolio_id: str,
    findings: list[TWRInspectionFinding],
    overlapping_dates: list[str],
    position_rows: list[dict[str, object]],
    selected_position_rows: list[dict[str, object]],
    mixed_epoch_dates: list[str],
    duplicate_snapshot_samples: list[dict[str, object]],
    invalid_epoch_samples: list[dict[str, object]],
    invalid_position_value_samples: list[dict[str, object]],
    gap_details: list[dict[str, object]],
    max_abs_gap_amount: Decimal,
    position_continuity_gap_samples: list[dict[str, object]],
) -> ReconciliationCheckResult:
    duplicate_snapshot_dates = {sample["valuation_date"] for sample in duplicate_snapshot_samples}
    invalid_position_epoch_dates = {sample["valuation_date"] for sample in invalid_epoch_samples}
    invalid_position_value_dates = {sample["valuation_date"] for sample in invalid_position_value_samples}
    return ReconciliationCheckResult(
        findings=findings,
        evidence_summary={
            "reconciliation_dates_checked": len(overlapping_dates),
            "position_row_count": len(position_rows),
            "selected_position_row_count": len(selected_position_rows),
            "mixed_epoch_date_count": len(mixed_epoch_dates),
            "duplicate_snapshot_date_count": len(duplicate_snapshot_dates),
            "duplicate_snapshot_row_count": len(duplicate_snapshot_samples),
            "invalid_position_epoch_date_count": len(invalid_position_epoch_dates),
            "invalid_position_epoch_row_count": len(invalid_epoch_samples),
            "invalid_position_value_date_count": len(invalid_position_value_dates),
            "invalid_position_value_row_count": len(invalid_position_value_samples),
            "reconciliation_gap_date_count": len(gap_details),
            "reconciliation_max_gap_amount": _decimal_to_artifact(max_abs_gap_amount),
            "position_continuity_gap_count": len(position_continuity_gap_samples),
        },
        artifact_payload={
            "portfolio_id": portfolio_id,
            "reconciliation_dates_checked": len(overlapping_dates),
            "position_row_count": len(position_rows),
            "selected_position_row_count": len(selected_position_rows),
            "mixed_epoch_dates": mixed_epoch_dates,
            "mixed_epoch_date_count": len(mixed_epoch_dates),
            "duplicate_snapshot_date_count": len(duplicate_snapshot_dates),
            "duplicate_snapshot_row_count": len(duplicate_snapshot_samples),
            "duplicate_snapshot_samples": duplicate_snapshot_samples[:25],
            "invalid_position_epoch_date_count": len(invalid_position_epoch_dates),
            "invalid_position_epoch_row_count": len(invalid_epoch_samples),
            "invalid_position_epoch_samples": invalid_epoch_samples[:25],
            "invalid_position_value_date_count": len(invalid_position_value_dates),
            "invalid_position_value_row_count": len(invalid_position_value_samples),
            "invalid_position_value_samples": invalid_position_value_samples[:25],
            "reconciliation_gap_date_count": len(gap_details),
            "max_gap_amount": _decimal_to_artifact(max_abs_gap_amount),
            "gap_samples": gap_details[:_RECONCILIATION_SAMPLE_LIMIT],
            "position_continuity_gap_count": len(position_continuity_gap_samples),
            "position_continuity_gap_samples": position_continuity_gap_samples[:_RECONCILIATION_SAMPLE_LIMIT],
        },
    )


def _analyze_position_reconciliation_gaps(
    *,
    portfolio_end_by_date: dict[str, Decimal],
    position_end_by_date: dict[str, Decimal],
) -> _PositionReconciliationGapAnalysis:
    overlapping_dates = sorted(set(portfolio_end_by_date) & set(position_end_by_date))
    gap_details: list[dict[str, object]] = []
    max_abs_gap_amount = Decimal("0")
    for valuation_date in overlapping_dates:
        portfolio_end = portfolio_end_by_date[valuation_date]
        position_end = position_end_by_date[valuation_date]
        gap_amount = portfolio_end - position_end
        tolerance = max(_ABSOLUTE_GAP_TOLERANCE, abs(portfolio_end) * _RELATIVE_GAP_TOLERANCE)
        if abs(gap_amount) <= tolerance:
            continue
        max_abs_gap_amount = max(max_abs_gap_amount, abs(gap_amount))
        gap_pct = None
        if portfolio_end != 0:
            gap_pct = _decimal_pct_to_float((gap_amount / portfolio_end) * Decimal("100"))
        gap_details.append(
            {
                "valuation_date": valuation_date,
                "portfolio_end_mv": _decimal_to_artifact(portfolio_end),
                "latest_position_end_mv": _decimal_to_artifact(position_end),
                "gap_amount": _decimal_to_artifact(gap_amount),
                "gap_pct_of_portfolio_end": gap_pct,
            }
        )
    return _PositionReconciliationGapAnalysis(
        overlapping_dates=overlapping_dates,
        gap_details=gap_details,
        max_abs_gap_amount=max_abs_gap_amount,
    )


def _select_latest_position_rows(position_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: _PositionRowSelection = {}
    for row in position_rows:
        _select_latest_position_row(selected, row)
    return [row for _, row in selected.values()]


def _select_latest_position_row(selected: _PositionRowSelection, row: dict[str, object]) -> None:
    key = _position_row_selection_key(row)
    if key is None:
        return
    epoch = _parse_epoch_value(row)
    current = selected.get(key)
    if _should_replace_selected_position_row(candidate_epoch=epoch, selected=current):
        selected[key] = (epoch, row)


def _should_replace_selected_position_row(
    *,
    candidate_epoch: int,
    selected: tuple[int, dict[str, object]] | None,
) -> bool:
    return selected is None or candidate_epoch >= selected[0]


def _position_row_selection_key(row: dict[str, object]) -> tuple[str, str] | None:
    valuation_date = row.get("valuation_date")
    position_id = row.get("position_id")
    if not isinstance(valuation_date, str) or not isinstance(position_id, str):
        return None
    return valuation_date, position_id


def _position_rows_from_payload(position_payload: dict[str, object]) -> list[dict[str, object]]:
    rows = position_payload.get("rows", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _find_mixed_epoch_dates(position_rows: list[dict[str, object]]) -> set[str]:
    epochs_by_date: dict[str, set[int]] = {}
    for row in position_rows:
        _record_position_epoch_by_date(epochs_by_date, row)
    return {valuation_date for valuation_date, epochs in epochs_by_date.items() if len(epochs) > 1}


def _record_position_epoch_by_date(epochs_by_date: dict[str, set[int]], row: dict[str, object]) -> None:
    valuation_date = row.get("valuation_date")
    if not isinstance(valuation_date, str):
        return
    epochs_by_date.setdefault(valuation_date, set()).add(_parse_epoch_value(row))


def _sum_position_end_values_by_date(
    position_rows: list[dict[str, object]],
) -> tuple[dict[str, Decimal], list[dict[str, object]]]:
    totals: dict[str, Decimal] = {}
    invalid_samples: list[dict[str, object]] = []
    for row in position_rows:
        valuation_date = row.get("valuation_date")
        if not isinstance(valuation_date, str):
            continue
        end_value_field, raw_end_value = _select_position_end_value_field(row)
        end_value = _parse_decimal(raw_end_value)
        if end_value is None:
            invalid_samples.append(
                {
                    "valuation_date": valuation_date,
                    "position_id": row.get("position_id"),
                    "valuation_epoch": _parse_epoch_value(row),
                    "end_value_field": end_value_field,
                    "raw_end_value": raw_end_value,
                }
            )
            continue
        totals[valuation_date] = totals.get(valuation_date, Decimal("0")) + end_value
    return totals, invalid_samples


def _select_position_end_value_field(row: dict[str, object]) -> tuple[str, object]:
    if row.get("ending_market_value_reporting_currency") is not None:
        return "ending_market_value_reporting_currency", row.get("ending_market_value_reporting_currency")
    return "ending_market_value_portfolio_currency", row.get("ending_market_value_portfolio_currency")


def _select_position_begin_value_field(row: dict[str, object]) -> tuple[str, object]:
    if row.get("beginning_market_value_reporting_currency") is not None:
        return "beginning_market_value_reporting_currency", row.get("beginning_market_value_reporting_currency")
    return "beginning_market_value_portfolio_currency", row.get("beginning_market_value_portfolio_currency")


def _collect_position_continuity_gap_samples(position_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for position_id, previous_row, current_row in _iter_position_continuity_pairs(position_rows):
        sample = _build_position_continuity_gap_sample(
            position_id=position_id,
            previous_row=previous_row,
            current_row=current_row,
        )
        if sample is not None:
            samples.append(sample)
    return samples


def _iter_position_continuity_pairs(position_rows: list[dict[str, object]]) -> Iterator[_PositionContinuityPair]:
    rows_by_position = _position_rows_by_position_id(position_rows)
    for position_id, rows in rows_by_position.items():
        sorted_rows = sorted(rows, key=lambda row: str(row.get("valuation_date")))
        previous_row: dict[str, object] | None = None
        for row in sorted_rows:
            if previous_row is not None:
                yield position_id, previous_row, row
            previous_row = row


def _position_rows_by_position_id(position_rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    rows_by_position: dict[str, list[dict[str, object]]] = {}
    for row in position_rows:
        position_id = row.get("position_id")
        valuation_date = row.get("valuation_date")
        if not isinstance(position_id, str) or not isinstance(valuation_date, str):
            continue
        rows_by_position.setdefault(position_id, []).append(row)
    return rows_by_position


def _build_position_continuity_gap_sample(
    *,
    position_id: str,
    previous_row: dict[str, object],
    current_row: dict[str, object],
) -> dict[str, object] | None:
    continuity_gap = _material_position_continuity_gap(
        previous_row=previous_row,
        current_row=current_row,
    )
    if continuity_gap is None:
        return None
    return _position_continuity_gap_sample_payload(
        position_id=position_id,
        previous_row=previous_row,
        current_row=current_row,
        continuity_gap=continuity_gap,
    )


def _material_position_continuity_gap(
    *,
    previous_row: dict[str, object],
    current_row: dict[str, object],
) -> _PositionContinuityGap | None:
    continuity_values = _position_continuity_values(
        previous_row=previous_row,
        current_row=current_row,
    )
    if continuity_values is None:
        return None
    gap_amount = _material_position_continuity_gap_amount(continuity_values)
    if gap_amount is None:
        return None
    if _row_has_transition_activity(current_row):
        return None
    return _PositionContinuityGap(
        values=continuity_values,
        gap_amount=gap_amount,
        gap_pct_of_previous_end=_position_continuity_gap_pct(
            gap_amount=gap_amount,
            previous_end=continuity_values.previous_end,
        ),
    )


def _material_position_continuity_gap_amount(
    continuity_values: _PositionContinuityValues,
) -> Decimal | None:
    gap_amount = continuity_values.current_begin - continuity_values.previous_end
    tolerance = max(
        _ABSOLUTE_GAP_TOLERANCE,
        abs(continuity_values.previous_end) * _RELATIVE_GAP_TOLERANCE,
    )
    if abs(gap_amount) <= tolerance:
        return None
    return gap_amount


def _position_continuity_gap_pct(  # monetary-float-allow
    *, gap_amount: Decimal, previous_end: Decimal
) -> float | None:
    if previous_end == 0:
        return None
    return _decimal_pct_to_float((gap_amount / previous_end) * Decimal("100"))


def _position_continuity_gap_sample_payload(
    *,
    position_id: str,
    previous_row: dict[str, object],
    current_row: dict[str, object],
    continuity_gap: _PositionContinuityGap,
) -> dict[str, object]:
    continuity_values = continuity_gap.values
    return {
        "position_id": position_id,
        "previous_valuation_date": previous_row.get("valuation_date"),
        "valuation_date": current_row.get("valuation_date"),
        "previous_end_value_field": continuity_values.previous_end_field,
        "current_begin_value_field": continuity_values.current_begin_field,
        "previous_end_value": _decimal_to_artifact(continuity_values.previous_end),
        "current_begin_value": _decimal_to_artifact(continuity_values.current_begin),
        "gap_amount": _decimal_to_artifact(continuity_gap.gap_amount),
        "gap_pct_of_previous_end": continuity_gap.gap_pct_of_previous_end,
    }


def _position_continuity_values(
    *,
    previous_row: dict[str, object],
    current_row: dict[str, object],
) -> _PositionContinuityValues | None:
    previous_end_field, raw_previous_end = _select_position_continuity_end_value_field(previous_row)
    current_begin_field, raw_current_begin = _select_position_continuity_begin_value_field(current_row)
    previous_end = _parse_decimal(raw_previous_end)
    current_begin = _parse_decimal(raw_current_begin)
    if previous_end is None or current_begin is None:
        return None
    return _PositionContinuityValues(
        previous_end_field=previous_end_field,
        previous_end=previous_end,
        current_begin_field=current_begin_field,
        current_begin=current_begin,
    )


def _row_has_transition_activity(row: dict[str, object]) -> bool:
    if _cash_flows_have_nonzero_amount(row.get("cash_flows")):
        return True
    for key, value in row.items():
        if _field_has_nonzero_transition_activity(key, value):
            return True
    return False


def _field_has_nonzero_transition_activity(key: str, value: object) -> bool:
    if not _is_transition_activity_field(key):
        return False
    decimal_value = _parse_decimal(value)
    return decimal_value is not None and decimal_value != 0


def _is_transition_activity_field(key: str) -> bool:
    normalized_key = key.lower()
    return normalized_key != "cash_flows" and any(
        token in normalized_key for token in _TRANSITION_ACTIVITY_FIELD_TOKENS
    )


def _select_position_continuity_end_value_field(row: dict[str, object]) -> tuple[str, object]:
    if row.get("ending_market_value_position_currency") is not None:
        return "ending_market_value_position_currency", row.get("ending_market_value_position_currency")
    return _select_position_end_value_field(row)


def _select_position_continuity_begin_value_field(row: dict[str, object]) -> tuple[str, object]:
    if row.get("beginning_market_value_position_currency") is not None:
        return "beginning_market_value_position_currency", row.get("beginning_market_value_position_currency")
    return _select_position_begin_value_field(row)


def _cash_flows_have_nonzero_amount(cash_flows: object) -> bool:
    if not isinstance(cash_flows, list):
        return False
    for flow in cash_flows:
        if _cash_flow_has_nonzero_amount(flow):
            return True
    return False


def _cash_flow_has_nonzero_amount(flow: object) -> bool:
    if not isinstance(flow, dict):
        return False
    amount = _parse_decimal(flow.get("amount"))
    return amount is not None and amount != 0


def _collect_duplicate_snapshot_samples(position_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    sample_state = _DuplicateSnapshotSamples(counts={}, sample_index_by_key={}, samples=[])
    for row in position_rows:
        _record_duplicate_snapshot_sample(sample_state, row)
    return sample_state.samples


def _record_duplicate_snapshot_sample(sample_state: _DuplicateSnapshotSamples, row: dict[str, object]) -> None:
    key = _duplicate_snapshot_key(row)
    if key is None:
        return
    duplicate_count = sample_state.counts.get(key, 0) + 1
    sample_state.counts[key] = duplicate_count
    _sync_duplicate_snapshot_sample(sample_state, key, duplicate_count)


def _sync_duplicate_snapshot_sample(
    sample_state: _DuplicateSnapshotSamples, key: _DuplicateSnapshotKey, duplicate_count: int
) -> None:
    if duplicate_count == 2:
        sample_state.samples.append(_duplicate_snapshot_sample_payload(key, duplicate_count))
        sample_state.sample_index_by_key[key] = len(sample_state.samples) - 1
    elif duplicate_count > 2:
        sample_state.samples[sample_state.sample_index_by_key[key]]["duplicate_count"] = duplicate_count


def _duplicate_snapshot_sample_payload(key: _DuplicateSnapshotKey, duplicate_count: int) -> dict[str, object]:
    valuation_date, position_id, epoch = key
    return {
        "valuation_date": valuation_date,
        "position_id": position_id,
        "valuation_epoch": epoch,
        "duplicate_count": duplicate_count,
    }


def _duplicate_snapshot_key(row: dict[str, object]) -> _DuplicateSnapshotKey | None:
    valuation_date = row.get("valuation_date")
    position_id = row.get("position_id")
    if not isinstance(valuation_date, str) or not isinstance(position_id, str):
        return None
    return valuation_date, position_id, _parse_epoch_value(row)


def _collect_invalid_epoch_samples(position_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    invalid_samples: list[dict[str, object]] = []
    for row in position_rows:
        valuation_date = row.get("valuation_date")
        position_id = row.get("position_id")
        epoch_value, invalid_epoch, epoch_field, raw_epoch_value = _parse_epoch_details(row)
        del epoch_value
        if not invalid_epoch or not isinstance(valuation_date, str):
            continue
        invalid_samples.append(
            {
                "valuation_date": valuation_date,
                "position_id": position_id,
                "epoch_field": epoch_field,
                "raw_epoch_value": raw_epoch_value,
            }
        )
    return invalid_samples


def _parse_epoch_value(row: dict[str, object]) -> int:
    epoch_value, _, _, _ = _parse_epoch_details(row)
    return epoch_value


def _parse_epoch_details(row: dict[str, object]) -> tuple[int, bool, str | None, object]:
    for key in ("valuation_epoch", "snapshot_epoch", "epoch"):
        raw_value = row.get(key)
        if raw_value is None:
            continue
        try:
            return int(str(raw_value)), False, key, raw_value
        except (TypeError, ValueError):
            return 0, True, key, raw_value
    return 0, False, None, None


def _parse_decimal(raw_value: object) -> Decimal | None:
    if raw_value is None:
        return None
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        return None
