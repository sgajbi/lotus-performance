from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.config import Settings, get_settings
from app.models.inspection_responses import TWRInspectionFinding
from app.models.requests import PerformanceRequest
from app.services.inspection.source_economics_collector import collect_source_economics_samples
from app.services.inspection.source_economics_findings import build_source_economics_findings
from app.services.portfolio_source_service import build_stateful_input_service

_INSPECTOR_CONSUMER_SYSTEM = "lotus-performance-inspector"
_CANONICAL_CASHFLOW_TYPES = {"fee", "external_flow"}
_SAMPLE_LIMIT = 25


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
    invalid_explicit_amount_fields: tuple[dict[str, object], ...]
    invalid_amount_rows: tuple[dict[str, object], ...]
    invalid_timing_rows: tuple[dict[str, object], ...]
    missing_cashflow_type_rows: tuple[dict[str, object], ...]
    noncanonical_cashflow_types: tuple[str, ...]


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
    samples = collect_source_economics_samples(source_points)

    findings = build_source_economics_findings(
        portfolio_id=portfolio_id,
        fee_normalization_samples=samples.fee_normalization_samples,
        duplicate_fee_signal_samples=samples.duplicate_fee_signal_samples,
        fee_source_mismatch_samples=samples.fee_source_mismatch_samples,
        positive_fee_signal_samples=samples.positive_fee_signal_samples,
        external_normalization_samples=samples.external_normalization_samples,
        duplicate_external_signal_samples=samples.duplicate_external_signal_samples,
        external_source_mismatch_samples=samples.external_source_mismatch_samples,
        external_timing_contradiction_samples=samples.external_timing_contradiction_samples,
        invalid_explicit_amount_samples=samples.invalid_explicit_amount_samples,
        invalid_amount_samples=samples.invalid_amount_samples,
        invalid_timing_samples=samples.invalid_timing_samples,
        missing_cashflow_type_samples=samples.missing_cashflow_type_samples,
        noncanonical_cashflow_type_samples=samples.noncanonical_cashflow_type_samples,
    )

    return SourceEconomicsCheckResult(
        findings=findings,
        evidence_summary=_build_evidence_summary(
            observations=observations,
            fee_flow_dates=samples.fee_flow_dates,
            external_flow_dates=samples.external_flow_dates,
            fee_normalization_samples=samples.fee_normalization_samples,
            duplicate_fee_signal_samples=samples.duplicate_fee_signal_samples,
            fee_source_mismatch_samples=samples.fee_source_mismatch_samples,
            positive_fee_signal_samples=samples.positive_fee_signal_samples,
            external_normalization_samples=samples.external_normalization_samples,
            duplicate_external_signal_samples=samples.duplicate_external_signal_samples,
            external_source_mismatch_samples=samples.external_source_mismatch_samples,
            external_timing_contradiction_samples=samples.external_timing_contradiction_samples,
            invalid_explicit_amount_samples=samples.invalid_explicit_amount_samples,
            invalid_amount_samples=samples.invalid_amount_samples,
            invalid_timing_samples=samples.invalid_timing_samples,
            missing_cashflow_type_samples=samples.missing_cashflow_type_samples,
            noncanonical_cashflow_type_samples=samples.noncanonical_cashflow_type_samples,
        ),
        artifact_payload=_build_artifact_payload(
            portfolio_id=portfolio_id,
            observations=observations,
            fee_flow_dates=samples.fee_flow_dates,
            external_flow_dates=samples.external_flow_dates,
            fee_normalization_samples=samples.fee_normalization_samples,
            duplicate_fee_signal_samples=samples.duplicate_fee_signal_samples,
            fee_source_mismatch_samples=samples.fee_source_mismatch_samples,
            positive_fee_signal_samples=samples.positive_fee_signal_samples,
            external_normalization_samples=samples.external_normalization_samples,
            duplicate_external_signal_samples=samples.duplicate_external_signal_samples,
            external_source_mismatch_samples=samples.external_source_mismatch_samples,
            external_timing_contradiction_samples=samples.external_timing_contradiction_samples,
            invalid_explicit_amount_samples=samples.invalid_explicit_amount_samples,
            invalid_amount_samples=samples.invalid_amount_samples,
            invalid_timing_samples=samples.invalid_timing_samples,
            missing_cashflow_type_samples=samples.missing_cashflow_type_samples,
            noncanonical_cashflow_type_samples=samples.noncanonical_cashflow_type_samples,
        ),
    )


def _build_evidence_summary(
    *,
    observations: list[dict[str, object]],
    fee_flow_dates: list[str],
    external_flow_dates: list[str],
    fee_normalization_samples: list[dict[str, object]],
    duplicate_fee_signal_samples: list[dict[str, object]],
    fee_source_mismatch_samples: list[dict[str, object]],
    positive_fee_signal_samples: list[dict[str, object]],
    external_normalization_samples: list[dict[str, object]],
    duplicate_external_signal_samples: list[dict[str, object]],
    external_source_mismatch_samples: list[dict[str, object]],
    external_timing_contradiction_samples: list[dict[str, object]],
    invalid_explicit_amount_samples: list[dict[str, object]],
    invalid_amount_samples: list[dict[str, object]],
    invalid_timing_samples: list[dict[str, object]],
    missing_cashflow_type_samples: list[dict[str, object]],
    noncanonical_cashflow_type_samples: list[dict[str, object]],
) -> dict[str, object]:
    return {
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
        "external_cashflow_timing_contradiction_count": len(external_timing_contradiction_samples),
        "invalid_explicit_source_amount_date_count": len(invalid_explicit_amount_samples),
        "invalid_cashflow_amount_date_count": len(invalid_amount_samples),
        "invalid_cashflow_timing_date_count": len(invalid_timing_samples),
        "missing_cashflow_type_date_count": len(missing_cashflow_type_samples),
        "noncanonical_cashflow_type_date_count": len(noncanonical_cashflow_type_samples),
    }


def _build_artifact_payload(
    *,
    portfolio_id: str,
    observations: list[dict[str, object]],
    fee_flow_dates: list[str],
    external_flow_dates: list[str],
    fee_normalization_samples: list[dict[str, object]],
    duplicate_fee_signal_samples: list[dict[str, object]],
    fee_source_mismatch_samples: list[dict[str, object]],
    positive_fee_signal_samples: list[dict[str, object]],
    external_normalization_samples: list[dict[str, object]],
    duplicate_external_signal_samples: list[dict[str, object]],
    external_source_mismatch_samples: list[dict[str, object]],
    external_timing_contradiction_samples: list[dict[str, object]],
    invalid_explicit_amount_samples: list[dict[str, object]],
    invalid_amount_samples: list[dict[str, object]],
    invalid_timing_samples: list[dict[str, object]],
    missing_cashflow_type_samples: list[dict[str, object]],
    noncanonical_cashflow_type_samples: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "portfolio_id": portfolio_id,
        "portfolio_observation_count": len(observations),
        "fee_cashflow_dates": fee_flow_dates,
        "external_cashflow_dates": external_flow_dates,
        "fee_cashflow_date_count": len(fee_flow_dates),
        "external_cashflow_date_count": len(external_flow_dates),
        "fee_normalization_gap_count": len(fee_normalization_samples),
        "fee_normalization_gap_samples": fee_normalization_samples[:_SAMPLE_LIMIT],
        "duplicate_fee_signal_count": len(duplicate_fee_signal_samples),
        "duplicate_fee_signal_samples": duplicate_fee_signal_samples[:_SAMPLE_LIMIT],
        "fee_source_mismatch_count": len(fee_source_mismatch_samples),
        "fee_source_mismatch_samples": fee_source_mismatch_samples[:_SAMPLE_LIMIT],
        "positive_fee_signal_count": len(positive_fee_signal_samples),
        "positive_fee_signal_samples": positive_fee_signal_samples[:_SAMPLE_LIMIT],
        "external_cashflow_normalization_gap_count": len(external_normalization_samples),
        "external_cashflow_normalization_gap_samples": external_normalization_samples[:_SAMPLE_LIMIT],
        "duplicate_external_cashflow_signal_count": len(duplicate_external_signal_samples),
        "duplicate_external_cashflow_signal_samples": duplicate_external_signal_samples[:_SAMPLE_LIMIT],
        "external_cashflow_source_mismatch_count": len(external_source_mismatch_samples),
        "external_cashflow_source_mismatch_samples": external_source_mismatch_samples[:_SAMPLE_LIMIT],
        "external_cashflow_timing_contradiction_count": len(external_timing_contradiction_samples),
        "external_cashflow_timing_contradiction_samples": external_timing_contradiction_samples[:_SAMPLE_LIMIT],
        "invalid_explicit_source_amount_date_count": len(invalid_explicit_amount_samples),
        "invalid_explicit_source_amount_samples": invalid_explicit_amount_samples[:_SAMPLE_LIMIT],
        "invalid_cashflow_amount_date_count": len(invalid_amount_samples),
        "invalid_cashflow_amount_samples": invalid_amount_samples[:_SAMPLE_LIMIT],
        "invalid_cashflow_timing_date_count": len(invalid_timing_samples),
        "invalid_cashflow_timing_samples": invalid_timing_samples[:_SAMPLE_LIMIT],
        "missing_cashflow_type_date_count": len(missing_cashflow_type_samples),
        "missing_cashflow_type_samples": missing_cashflow_type_samples[:_SAMPLE_LIMIT],
        "noncanonical_cashflow_type_date_count": len(noncanonical_cashflow_type_samples),
        "noncanonical_cashflow_type_samples": noncanonical_cashflow_type_samples[:_SAMPLE_LIMIT],
        "noncanonical_cashflow_types": _collect_noncanonical_cashflow_types(noncanonical_cashflow_type_samples),
    }


def _collect_noncanonical_cashflow_types(
    noncanonical_cashflow_type_samples: list[dict[str, object]],
) -> list[str]:
    return sorted(
        {
            cash_flow_type
            for sample in noncanonical_cashflow_type_samples
            for cash_flow_type in sample["cash_flow_types"]
        }
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
        (
            detailed_external_bod,
            detailed_external_eod,
            detailed_fee_bod,
            detailed_fee_eod,
            explicit_bod_total,
            explicit_eod_total,
            explicit_fee_total,
            invalid_explicit_amount_fields,
            invalid_amount_rows,
            invalid_timing_rows,
            missing_cashflow_type_rows,
            noncanonical_cashflow_types,
        ) = _collect_observation_economics(observation)
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
                explicit_bod_total=explicit_bod_total,
                explicit_eod_total=explicit_eod_total,
                explicit_fee_total=explicit_fee_total,
                invalid_explicit_amount_fields=invalid_explicit_amount_fields,
                invalid_amount_rows=invalid_amount_rows,
                invalid_timing_rows=invalid_timing_rows,
                missing_cashflow_type_rows=missing_cashflow_type_rows,
                noncanonical_cashflow_types=noncanonical_cashflow_types,
            )
        )
    return source_points


def _collect_observation_economics(
    observation: dict[str, object],
) -> tuple[
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal | None,
    Decimal | None,
    Decimal | None,
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[str, ...],
]:
    (
        detailed_external_bod,
        detailed_external_eod,
        detailed_fee_bod,
        detailed_fee_eod,
        invalid_amount_rows,
        invalid_timing_rows,
        missing_cashflow_type_rows,
        noncanonical_cashflow_types,
    ) = _sum_detailed_cash_flows(observation.get("cash_flows"))
    explicit_bod_total, invalid_bod_fields = _read_explicit_decimal_fields(
        observation,
        semantic="bod_cashflow_total",
        keys=("bod_cashflow", "beginning_cash_flow"),
    )
    explicit_eod_total, invalid_eod_fields = _read_explicit_decimal_fields(
        observation,
        semantic="eod_cashflow_total",
        keys=("eod_cashflow", "ending_cash_flow"),
    )
    explicit_fee_total, invalid_fee_fields = _read_explicit_decimal_fields(
        observation,
        semantic="fee_total",
        keys=("fees", "management_fees"),
    )
    return (
        detailed_external_bod,
        detailed_external_eod,
        detailed_fee_bod,
        detailed_fee_eod,
        explicit_bod_total,
        explicit_eod_total,
        explicit_fee_total,
        invalid_bod_fields + invalid_eod_fields + invalid_fee_fields,
        invalid_amount_rows,
        invalid_timing_rows,
        missing_cashflow_type_rows,
        noncanonical_cashflow_types,
    )


def _sum_detailed_cash_flows(
    cash_flows_raw: object,
) -> tuple[
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[str, ...],
]:
    external_bod = Decimal("0")
    external_eod = Decimal("0")
    fee_bod = Decimal("0")
    fee_eod = Decimal("0")
    invalid_amount_rows: list[dict[str, object]] = []
    invalid_timing_rows: list[dict[str, object]] = []
    missing_cashflow_type_rows: list[dict[str, object]] = []
    noncanonical_cashflow_types: set[str] = set()
    if not isinstance(cash_flows_raw, list):
        return external_bod, external_eod, fee_bod, fee_eod, (), (), (), ()

    for flow in cash_flows_raw:
        if not isinstance(flow, dict):
            continue
        timing = flow.get("timing")
        cash_flow_type = flow.get("cash_flow_type")
        raw_amount = flow.get("amount")
        amount = _parse_decimal(raw_amount)
        normalized_timing = timing.strip() if isinstance(timing, str) else timing
        if amount is None:
            invalid_amount_rows.append(
                {
                    "timing": normalized_timing,
                    "amount": raw_amount,
                    "cash_flow_type": cash_flow_type,
                }
            )
            continue
        if normalized_timing not in {"bod", "eod"}:
            invalid_timing_rows.append(
                {
                    "timing": normalized_timing,
                    "amount": float(amount),
                    "cash_flow_type": cash_flow_type,
                }
            )
            continue
        normalized_cash_flow_type = cash_flow_type.strip() if isinstance(cash_flow_type, str) else cash_flow_type
        if normalized_cash_flow_type is None or normalized_cash_flow_type == "":
            missing_cashflow_type_rows.append({"timing": normalized_timing, "amount": float(amount)})
        if (
            isinstance(normalized_cash_flow_type, str)
            and normalized_cash_flow_type
            and normalized_cash_flow_type not in _CANONICAL_CASHFLOW_TYPES
        ):
            noncanonical_cashflow_types.add(normalized_cash_flow_type)
        if normalized_cash_flow_type == "fee":
            if normalized_timing == "bod":
                fee_bod += amount
            else:
                fee_eod += amount
            continue
        if normalized_timing == "bod":
            external_bod += amount
        else:
            external_eod += amount
    return (
        external_bod,
        external_eod,
        fee_bod,
        fee_eod,
        tuple(invalid_amount_rows),
        tuple(invalid_timing_rows),
        tuple(missing_cashflow_type_rows),
        tuple(sorted(noncanonical_cashflow_types)),
    )


def _read_explicit_decimal_fields(
    observation: dict[str, object],
    *,
    semantic: str,
    keys: tuple[str, ...],
) -> tuple[Decimal | None, tuple[dict[str, object], ...]]:
    decimal_value: Decimal | None = None
    invalid_fields: list[dict[str, object]] = []
    for key in keys:
        raw_value = observation.get(key)
        if raw_value is None:
            continue
        parsed_value = _parse_decimal(raw_value)
        if parsed_value is not None:
            if decimal_value is None:
                decimal_value = parsed_value
            continue
        invalid_fields.append({"field": key, "semantic": semantic, "raw_value": raw_value})
    return decimal_value, tuple(invalid_fields)


def _parse_decimal(raw_value: object) -> Decimal | None:
    if raw_value is None:
        return None
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        return None
