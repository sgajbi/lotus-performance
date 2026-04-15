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


@dataclass(frozen=True)
class ObservationSourceEconomics:
    valuation_date: str
    normalized_bod_cf: Decimal
    normalized_eod_cf: Decimal
    normalized_mgmt_fees: Decimal
    detailed_external_bod: Decimal
    detailed_external_eod: Decimal
    detailed_fee_bod: Decimal
    detailed_fee_eod: Decimal
    explicit_bod_total: Decimal | None
    explicit_eod_total: Decimal | None
    explicit_fee_total: Decimal | None


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
    source_points = _build_observation_source_economics(
        observations=observations,
        normalized_by_date=normalized_by_date,
    )

    fee_normalization_samples: list[dict[str, object]] = []
    duplicate_fee_signal_samples: list[dict[str, object]] = []
    fee_source_mismatch_samples: list[dict[str, object]] = []
    positive_fee_signal_samples: list[dict[str, object]] = []
    external_normalization_samples: list[dict[str, object]] = []
    duplicate_external_signal_samples: list[dict[str, object]] = []
    external_source_mismatch_samples: list[dict[str, object]] = []
    fee_flow_dates: list[str] = []
    external_flow_dates: list[str] = []

    for source_point in source_points:
        if source_point.detailed_fee_bod != 0 or source_point.detailed_fee_eod != 0:
            fee_flow_dates.append(source_point.valuation_date)
        if source_point.detailed_external_bod != 0 or source_point.detailed_external_eod != 0:
            external_flow_dates.append(source_point.valuation_date)

        expected_fee_total, fee_source_kind = _expected_fee_total(source_point)
        if expected_fee_total is not None and not _amounts_match(source_point.normalized_mgmt_fees, expected_fee_total):
            fee_normalization_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "raw_fee_bod": float(source_point.detailed_fee_bod),
                    "raw_fee_eod": float(source_point.detailed_fee_eod),
                    "expected_fee_amount": float(expected_fee_total),
                    "fee_source_kind": fee_source_kind,
                    "normalized_bod_cf": float(source_point.normalized_bod_cf),
                    "normalized_eod_cf": float(source_point.normalized_eod_cf),
                    "normalized_mgmt_fees": float(source_point.normalized_mgmt_fees),
                }
            )

        fee_total = source_point.detailed_fee_bod + source_point.detailed_fee_eod
        if source_point.explicit_fee_total is not None and _amounts_match(source_point.explicit_fee_total, fee_total):
            duplicate_fee_signal_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "explicit_fee_amount": float(source_point.explicit_fee_total),
                    "fee_cashflow_amount": float(fee_total),
                }
            )
        elif source_point.explicit_fee_total is not None and fee_total != 0:
            fee_source_mismatch_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "explicit_fee_amount": float(source_point.explicit_fee_total),
                    "fee_cashflow_amount": float(fee_total),
                }
            )
        if fee_total > 0 or (source_point.explicit_fee_total is not None and source_point.explicit_fee_total > 0):
            positive_fee_signal_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "detailed_fee_amount": float(fee_total),
                    "explicit_fee_amount": (
                        float(source_point.explicit_fee_total) if source_point.explicit_fee_total is not None else None
                    ),
                }
            )

        expected_external_bod, bod_source_kind = _expected_external_total(source_point, timing="bod")
        expected_external_eod, eod_source_kind = _expected_external_total(source_point, timing="eod")
        if (
            expected_external_bod is not None
            and not _amounts_match(source_point.normalized_bod_cf, expected_external_bod)
        ) or (
            expected_external_eod is not None
            and not _amounts_match(source_point.normalized_eod_cf, expected_external_eod)
        ):
            external_normalization_samples.append(
                {
                    "valuation_date": source_point.valuation_date,
                    "raw_external_bod": float(source_point.detailed_external_bod),
                    "raw_external_eod": float(source_point.detailed_external_eod),
                    "expected_external_bod": (
                        float(expected_external_bod) if expected_external_bod is not None else None
                    ),
                    "expected_external_eod": (
                        float(expected_external_eod) if expected_external_eod is not None else None
                    ),
                    "bod_source_kind": bod_source_kind,
                    "eod_source_kind": eod_source_kind,
                    "normalized_bod_cf": float(source_point.normalized_bod_cf),
                    "normalized_eod_cf": float(source_point.normalized_eod_cf),
                }
            )

        if source_point.explicit_bod_total is not None and source_point.detailed_external_bod != 0:
            _record_external_source_signal(
                sample_target=duplicate_external_signal_samples,
                mismatch_target=external_source_mismatch_samples,
                valuation_date=source_point.valuation_date,
                timing="bod",
                explicit_total=source_point.explicit_bod_total,
                detailed_total=source_point.detailed_external_bod,
            )
        if source_point.explicit_eod_total is not None and source_point.detailed_external_eod != 0:
            _record_external_source_signal(
                sample_target=duplicate_external_signal_samples,
                mismatch_target=external_source_mismatch_samples,
                valuation_date=source_point.valuation_date,
                timing="eod",
                explicit_total=source_point.explicit_eod_total,
                detailed_total=source_point.detailed_external_eod,
            )

    findings = _build_findings(
        portfolio_id=portfolio_id,
        fee_normalization_samples=fee_normalization_samples,
        duplicate_fee_signal_samples=duplicate_fee_signal_samples,
        fee_source_mismatch_samples=fee_source_mismatch_samples,
        positive_fee_signal_samples=positive_fee_signal_samples,
        external_normalization_samples=external_normalization_samples,
        duplicate_external_signal_samples=duplicate_external_signal_samples,
        external_source_mismatch_samples=external_source_mismatch_samples,
    )

    return SourceEconomicsCheckResult(
        findings=findings,
        evidence_summary={
            "portfolio_observation_count": len(observations),
            "fee_cashflow_date_count": len(fee_flow_dates),
            "external_cashflow_date_count": len(external_flow_dates),
            "fee_normalization_gap_count": len(fee_normalization_samples),
            "duplicate_fee_signal_count": len(duplicate_fee_signal_samples),
            "fee_source_mismatch_count": len(fee_source_mismatch_samples),
            "positive_fee_signal_count": len(positive_fee_signal_samples),
            "external_cashflow_normalization_gap_count": len(external_normalization_samples),
            "duplicate_external_cashflow_signal_count": len(duplicate_external_signal_samples),
            "external_cashflow_source_mismatch_count": len(external_source_mismatch_samples),
        },
        artifact_payload={
            "portfolio_id": portfolio_id,
            "portfolio_observation_count": len(observations),
            "fee_cashflow_dates": fee_flow_dates,
            "external_cashflow_dates": external_flow_dates,
            "fee_cashflow_date_count": len(fee_flow_dates),
            "external_cashflow_date_count": len(external_flow_dates),
            "fee_normalization_gap_count": len(fee_normalization_samples),
            "fee_normalization_gap_samples": fee_normalization_samples[:25],
            "duplicate_fee_signal_count": len(duplicate_fee_signal_samples),
            "duplicate_fee_signal_samples": duplicate_fee_signal_samples[:25],
            "fee_source_mismatch_count": len(fee_source_mismatch_samples),
            "fee_source_mismatch_samples": fee_source_mismatch_samples[:25],
            "positive_fee_signal_count": len(positive_fee_signal_samples),
            "positive_fee_signal_samples": positive_fee_signal_samples[:25],
            "external_cashflow_normalization_gap_count": len(external_normalization_samples),
            "external_cashflow_normalization_gap_samples": external_normalization_samples[:25],
            "duplicate_external_cashflow_signal_count": len(duplicate_external_signal_samples),
            "duplicate_external_cashflow_signal_samples": duplicate_external_signal_samples[:25],
            "external_cashflow_source_mismatch_count": len(external_source_mismatch_samples),
            "external_cashflow_source_mismatch_samples": external_source_mismatch_samples[:25],
        },
    )


def _build_observation_source_economics(
    *,
    observations: list[dict[str, object]],
    normalized_by_date: dict[str, dict[str, Decimal]],
) -> list[ObservationSourceEconomics]:
    source_points: list[ObservationSourceEconomics] = []
    for observation in observations:
        valuation_date = observation.get("valuation_date")
        if not isinstance(valuation_date, str):
            continue
        normalized_point = normalized_by_date.get(
            valuation_date,
            {"bod_cf": Decimal("0"), "eod_cf": Decimal("0"), "mgmt_fees": Decimal("0")},
        )
        detailed_external_bod, detailed_external_eod, detailed_fee_bod, detailed_fee_eod = _sum_detailed_cash_flows(
            observation.get("cash_flows")
        )
        source_points.append(
            ObservationSourceEconomics(
                valuation_date=valuation_date,
                normalized_bod_cf=normalized_point["bod_cf"],
                normalized_eod_cf=normalized_point["eod_cf"],
                normalized_mgmt_fees=normalized_point["mgmt_fees"],
                detailed_external_bod=detailed_external_bod,
                detailed_external_eod=detailed_external_eod,
                detailed_fee_bod=detailed_fee_bod,
                detailed_fee_eod=detailed_fee_eod,
                explicit_bod_total=_first_decimal(observation, "bod_cashflow", "beginning_cash_flow"),
                explicit_eod_total=_first_decimal(observation, "eod_cashflow", "ending_cash_flow"),
                explicit_fee_total=_first_decimal(observation, "fees", "management_fees"),
            )
        )
    return source_points


def _sum_detailed_cash_flows(cash_flows_raw: object) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    external_bod = Decimal("0")
    external_eod = Decimal("0")
    fee_bod = Decimal("0")
    fee_eod = Decimal("0")
    if not isinstance(cash_flows_raw, list):
        return external_bod, external_eod, fee_bod, fee_eod

    for flow in cash_flows_raw:
        if not isinstance(flow, dict):
            continue
        amount = _parse_decimal(flow.get("amount"))
        timing = flow.get("timing")
        if amount is None or timing not in {"bod", "eod"}:
            continue
        if flow.get("cash_flow_type") == "fee":
            if timing == "bod":
                fee_bod += amount
            else:
                fee_eod += amount
            continue
        if timing == "bod":
            external_bod += amount
        else:
            external_eod += amount
    return external_bod, external_eod, fee_bod, fee_eod


def _expected_fee_total(source_point: ObservationSourceEconomics) -> tuple[Decimal | None, str | None]:
    detailed_fee_total = source_point.detailed_fee_bod + source_point.detailed_fee_eod
    if detailed_fee_total != 0:
        return detailed_fee_total, "detailed_fee_cash_flows"
    if source_point.explicit_fee_total is not None:
        return source_point.explicit_fee_total, "explicit_fee_total"
    return None, None


def _expected_external_total(
    source_point: ObservationSourceEconomics,
    *,
    timing: str,
) -> tuple[Decimal | None, str | None]:
    detailed_total = source_point.detailed_external_bod if timing == "bod" else source_point.detailed_external_eod
    explicit_total = source_point.explicit_bod_total if timing == "bod" else source_point.explicit_eod_total
    if detailed_total != 0:
        return detailed_total, "detailed_external_cash_flows"
    if explicit_total is not None:
        return explicit_total, f"explicit_{timing}_cashflow_total"
    return None, None


def _record_external_source_signal(
    *,
    sample_target: list[dict[str, object]],
    mismatch_target: list[dict[str, object]],
    valuation_date: str,
    timing: str,
    explicit_total: Decimal,
    detailed_total: Decimal,
) -> None:
    sample = {
        "valuation_date": valuation_date,
        "timing": timing,
        "explicit_cashflow_amount": float(explicit_total),
        "detailed_cashflow_amount": float(detailed_total),
    }
    if _amounts_match(explicit_total, detailed_total):
        sample_target.append(sample)
    else:
        mismatch_target.append(sample)


def _build_findings(
    *,
    portfolio_id: str,
    fee_normalization_samples: list[dict[str, object]],
    duplicate_fee_signal_samples: list[dict[str, object]],
    fee_source_mismatch_samples: list[dict[str, object]],
    positive_fee_signal_samples: list[dict[str, object]],
    external_normalization_samples: list[dict[str, object]],
    duplicate_external_signal_samples: list[dict[str, object]],
    external_source_mismatch_samples: list[dict[str, object]],
) -> list[TWRInspectionFinding]:
    findings: list[TWRInspectionFinding] = []

    if fee_normalization_samples:
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

    if fee_source_mismatch_samples:
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
                evidence={
                    "portfolio_id": portfolio_id,
                    "sample_dates": [sample["valuation_date"] for sample in fee_source_mismatch_samples[:10]],
                    "samples": fee_source_mismatch_samples[:10],
                },
            )
        )

    if positive_fee_signal_samples:
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
                evidence={
                    "portfolio_id": portfolio_id,
                    "sample_dates": [sample["valuation_date"] for sample in positive_fee_signal_samples[:10]],
                    "samples": positive_fee_signal_samples[:10],
                },
            )
        )

    if external_normalization_samples:
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
                evidence={
                    "portfolio_id": portfolio_id,
                    "sample_dates": [sample["valuation_date"] for sample in external_normalization_samples[:10]],
                    "samples": external_normalization_samples[:10],
                },
            )
        )

    if duplicate_external_signal_samples:
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
                evidence={
                    "portfolio_id": portfolio_id,
                    "sample_dates": [sample["valuation_date"] for sample in duplicate_external_signal_samples[:10]],
                    "samples": duplicate_external_signal_samples[:10],
                },
            )
        )

    if external_source_mismatch_samples:
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
                evidence={
                    "portfolio_id": portfolio_id,
                    "sample_dates": [sample["valuation_date"] for sample in external_source_mismatch_samples[:10]],
                    "samples": external_source_mismatch_samples[:10],
                },
            )
        )

    return findings


def _first_decimal(observation: dict[str, object], *keys: str) -> Decimal | None:
    for key in keys:
        decimal_value = _parse_decimal(observation.get(key))
        if decimal_value is not None:
            return decimal_value
    return None


def _amounts_match(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= _ABSOLUTE_TOLERANCE


def _parse_decimal(raw_value: object) -> Decimal | None:
    if raw_value is None:
        return None
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        return None
