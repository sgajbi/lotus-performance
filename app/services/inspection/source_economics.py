from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.config import Settings, get_settings
from app.models.inspection_responses import TWRInspectionFinding
from app.models.requests import PerformanceRequest
from app.services.portfolio_source_service import build_stateful_input_service

_ABSOLUTE_TOLERANCE = Decimal("0.01")
_INSPECTOR_CONSUMER_SYSTEM = "lotus-performance-inspector"


@dataclass(frozen=True)
class SourceEconomicsCheckResult:
    findings: list[TWRInspectionFinding]
    evidence_summary: dict[str, object]
    artifact_payload: dict[str, object]


def run_source_economics_checks(
    *,
    performance_request: PerformanceRequest,
    portfolio_id: str,
    settings: Settings | None = None,
) -> SourceEconomicsCheckResult:
    portfolio_payload = asyncio.run(
        _fetch_portfolio_timeseries(
            performance_request=performance_request,
            portfolio_id=portfolio_id,
            settings=settings or get_settings(),
        )
    )
    return analyze_source_economics(
        performance_request=performance_request,
        portfolio_id=portfolio_id,
        observations=portfolio_payload.get("observations", []),
    )


async def _fetch_portfolio_timeseries(
    *,
    performance_request: PerformanceRequest,
    portfolio_id: str,
    settings: Settings,
) -> dict[str, object]:
    stateful_input_service = build_stateful_input_service(settings=settings)
    status_code, payload = await stateful_input_service.get_portfolio_timeseries(
        portfolio_id=portfolio_id,
        as_of_date=performance_request.report_end_date,
        start_date=performance_request.performance_start_date,
        end_date=performance_request.report_end_date,
        reporting_currency=performance_request.report_ccy,
        consumer_system=_INSPECTOR_CONSUMER_SYSTEM,
        calculation_id=None,
    )
    if status_code >= 400:
        raise RuntimeError(f"Portfolio timeseries source unavailable for source-economics inspection ({status_code}).")
    return payload


def analyze_source_economics(
    *,
    performance_request: PerformanceRequest,
    portfolio_id: str,
    observations: list[dict[str, object]],
) -> SourceEconomicsCheckResult:
    normalized_by_date = {
        point.perf_date.isoformat(): {
            "bod_cf": Decimal(str(point.bod_cf)),
            "eod_cf": Decimal(str(point.eod_cf)),
            "mgmt_fees": Decimal(str(point.mgmt_fees)),
        }
        for point in performance_request.valuation_points
    }

    fee_normalization_samples: list[dict[str, object]] = []
    duplicate_fee_signal_samples: list[dict[str, object]] = []
    fee_flow_dates: list[str] = []

    for observation in observations:
        valuation_date = observation.get("valuation_date")
        if not isinstance(valuation_date, str):
            continue

        fee_bod = Decimal("0")
        fee_eod = Decimal("0")
        cash_flows_raw = observation.get("cash_flows")
        if isinstance(cash_flows_raw, list):
            for flow in cash_flows_raw:
                if not isinstance(flow, dict) or flow.get("cash_flow_type") != "fee":
                    continue
                amount = _parse_decimal(flow.get("amount"))
                timing = flow.get("timing")
                if amount is None or timing not in {"bod", "eod"}:
                    continue
                if valuation_date not in fee_flow_dates:
                    fee_flow_dates.append(valuation_date)
                if timing == "bod":
                    fee_bod += amount
                else:
                    fee_eod += amount

        if fee_bod == 0 and fee_eod == 0:
            continue

        normalized_point = normalized_by_date.get(valuation_date)
        if normalized_point is not None and normalized_point["mgmt_fees"] == 0:
            fee_normalization_samples.append(
                {
                    "valuation_date": valuation_date,
                    "raw_fee_bod": float(fee_bod),
                    "raw_fee_eod": float(fee_eod),
                    "normalized_bod_cf": float(normalized_point["bod_cf"]),
                    "normalized_eod_cf": float(normalized_point["eod_cf"]),
                    "normalized_mgmt_fees": float(normalized_point["mgmt_fees"]),
                }
            )

        explicit_fee_amount = _parse_decimal(observation.get("fees"))
        if explicit_fee_amount is None:
            explicit_fee_amount = _parse_decimal(observation.get("management_fees"))
        if explicit_fee_amount is not None and abs(abs(explicit_fee_amount) - abs(fee_bod + fee_eod)) <= _ABSOLUTE_TOLERANCE:
            duplicate_fee_signal_samples.append(
                {
                    "valuation_date": valuation_date,
                    "explicit_fee_amount": float(explicit_fee_amount),
                    "fee_cashflow_amount": float(fee_bod + fee_eod),
                }
            )

    findings: list[TWRInspectionFinding] = []
    if fee_normalization_samples:
        findings.append(
            TWRInspectionFinding(
                code="FEE_CASHFLOW_CLASSIFICATION_NOT_PRESERVED",
                severity="high",
                category="cashflow_classification",
                owner_repo="lotus-performance",
                summary="Fee-classified source cash flows were normalized as ordinary portfolio cash flows.",
                explanation=(
                    "The stateful portfolio source includes fee-classified cash flows, but the normalized TWR "
                    "valuation points do not preserve those amounts in mgmt_fees."
                ),
                recommended_action=(
                    "Preserve fee-classified source economics during stateful portfolio normalization so fees do not "
                    "collapse into ordinary bod_cf or eod_cf terms."
                ),
                evidence={
                    "portfolio_id": portfolio_id,
                    "sample_dates": [sample["valuation_date"] for sample in fee_normalization_samples[:10]],
                    "samples": fee_normalization_samples[:10],
                },
            )
        )

    if duplicate_fee_signal_samples:
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
                evidence={
                    "portfolio_id": portfolio_id,
                    "sample_dates": [sample["valuation_date"] for sample in duplicate_fee_signal_samples[:10]],
                    "samples": duplicate_fee_signal_samples[:10],
                },
            )
        )

    return SourceEconomicsCheckResult(
        findings=findings,
        evidence_summary={
            "portfolio_observation_count": len(observations),
            "fee_cashflow_date_count": len(fee_flow_dates),
            "fee_normalization_gap_count": len(fee_normalization_samples),
            "duplicate_fee_signal_count": len(duplicate_fee_signal_samples),
        },
        artifact_payload={
            "portfolio_id": portfolio_id,
            "portfolio_observation_count": len(observations),
            "fee_cashflow_dates": fee_flow_dates,
            "fee_cashflow_date_count": len(fee_flow_dates),
            "fee_normalization_gap_count": len(fee_normalization_samples),
            "fee_normalization_gap_samples": fee_normalization_samples[:25],
            "duplicate_fee_signal_count": len(duplicate_fee_signal_samples),
            "duplicate_fee_signal_samples": duplicate_fee_signal_samples[:25],
        },
    )


def _parse_decimal(raw_value: object) -> Decimal | None:
    if raw_value is None:
        return None
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        return None
