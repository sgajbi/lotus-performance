from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.config import Settings, get_settings
from app.models.inspection_requests import TWRInspectionProfile
from app.models.inspection_responses import TWRInspectionFinding
from app.models.requests import PerformanceRequest
from app.services.portfolio_source_service import build_stateful_input_service

_ABSOLUTE_GAP_TOLERANCE = Decimal("0.01")
_RELATIVE_GAP_TOLERANCE = Decimal("0.0001")
_INSPECTOR_CONSUMER_SYSTEM = "lotus-performance-inspector"


@dataclass(frozen=True)
class ReconciliationCheckResult:
    findings: list[TWRInspectionFinding]
    evidence_summary: dict[str, object]


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
        position_rows=position_payload.get("rows", []),
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
        raise RuntimeError(f"Position timeseries source unavailable for reconciliation ({status_code}).")
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
        point.perf_date.isoformat(): Decimal(str(point.end_mv))
        for point in performance_request.valuation_points
    }
    selected_position_rows = _select_latest_position_rows(position_rows)
    position_end_by_date = _sum_position_end_values_by_date(selected_position_rows)

    mixed_epoch_dates = sorted(_find_mixed_epoch_dates(position_rows))
    findings: list[TWRInspectionFinding] = []

    if mixed_epoch_dates:
        findings.append(
            TWRInspectionFinding(
                code="MIXED_POSITION_EPOCH_SNAPSHOT",
                severity="high",
                category="epoch_coherence",
                owner_repo="lotus-core",
                summary="Position timeseries contains mixed snapshot epochs for the same valuation date.",
                explanation=(
                    "A coherent portfolio-state reconciliation requires one promoted snapshot state per valuation "
                    "date. The served position rows include multiple epochs on the same date."
                ),
                recommended_action=(
                    "Review lotus-core position snapshot promotion and ensure one coherent epoch is served per "
                    "portfolio date."
                ),
                evidence={
                    "portfolio_id": portfolio_id,
                    "mixed_epoch_dates": mixed_epoch_dates[:10],
                    "mixed_epoch_date_count": len(mixed_epoch_dates),
                },
            )
        )

    overlapping_dates = sorted(set(portfolio_end_by_date) & set(position_end_by_date))
    gap_details = []
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
            gap_pct = float((gap_amount / portfolio_end) * Decimal("100"))
        gap_details.append(
            {
                "valuation_date": valuation_date,
                "portfolio_end_mv": float(portfolio_end),
                "latest_position_end_mv": float(position_end),
                "gap_amount": float(gap_amount),
                "gap_pct_of_portfolio_end": gap_pct,
            }
        )

    if gap_details:
        findings.append(
            TWRInspectionFinding(
                code="PORTFOLIO_POSITION_RECONCILIATION_GAP",
                severity="high",
                category="portfolio_position_reconciliation",
                owner_repo="lotus-core",
                summary="Portfolio totals do not reconcile to the latest coherent position state.",
                explanation=(
                    "The served portfolio ending market value differs from the latest position-state total on one or "
                    "more inspected dates beyond the governed reconciliation tolerance."
                ),
                recommended_action=(
                    "Review lotus-core aggregate portfolio valuation assembly, position snapshot promotion, and "
                    "source-state reconciliation controls."
                ),
                evidence={
                    "portfolio_id": portfolio_id,
                    "reconciliation_gap_dates": [detail["valuation_date"] for detail in gap_details[:10]],
                    "gap_samples": gap_details[:10],
                    "max_gap_amount": float(max_abs_gap_amount),
                },
            )
        )

    return ReconciliationCheckResult(
        findings=findings,
        evidence_summary={
            "reconciliation_dates_checked": len(overlapping_dates),
            "position_row_count": len(position_rows),
            "selected_position_row_count": len(selected_position_rows),
            "mixed_epoch_date_count": len(mixed_epoch_dates),
            "reconciliation_gap_date_count": len(gap_details),
            "reconciliation_max_gap_amount": float(max_abs_gap_amount),
        },
    )


def _select_latest_position_rows(position_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: dict[tuple[str, str], tuple[int, dict[str, object]]] = {}
    for row in position_rows:
        valuation_date = row.get("valuation_date")
        position_id = row.get("position_id")
        if not isinstance(valuation_date, str) or not isinstance(position_id, str):
            continue
        epoch = _parse_epoch_value(row)
        key = (valuation_date, position_id)
        current = selected.get(key)
        if current is None or epoch >= current[0]:
            selected[key] = (epoch, row)
    return [row for _, row in selected.values()]


def _find_mixed_epoch_dates(position_rows: list[dict[str, object]]) -> set[str]:
    epochs_by_date: dict[str, set[int]] = {}
    for row in position_rows:
        valuation_date = row.get("valuation_date")
        if not isinstance(valuation_date, str):
            continue
        epochs_by_date.setdefault(valuation_date, set()).add(_parse_epoch_value(row))
    return {valuation_date for valuation_date, epochs in epochs_by_date.items() if len(epochs) > 1}


def _sum_position_end_values_by_date(position_rows: list[dict[str, object]]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in position_rows:
        valuation_date = row.get("valuation_date")
        if not isinstance(valuation_date, str):
            continue
        end_value = _parse_decimal(
            row.get("ending_market_value_reporting_currency")
            if row.get("ending_market_value_reporting_currency") is not None
            else row.get("ending_market_value_portfolio_currency")
        )
        if end_value is None:
            continue
        totals[valuation_date] = totals.get(valuation_date, Decimal("0")) + end_value
    return totals


def _parse_epoch_value(row: dict[str, object]) -> int:
    for key in ("valuation_epoch", "snapshot_epoch", "epoch"):
        raw_value = row.get(key)
        if raw_value is None:
            continue
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            continue
    return 0


def _parse_decimal(raw_value: object) -> Decimal | None:
    if raw_value is None:
        return None
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        return None
