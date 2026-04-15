from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from numbers import Real

from app.core.config import Settings, get_settings
from app.models.inspection_responses import TWRInspectionFinding
from app.models.requests import PerformanceRequest
from app.services.inspection.source_economics_collector import (
    SourceEconomicsSamples,
    collect_source_economics_samples,
)
from app.services.inspection.source_economics_findings import build_source_economics_findings
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.source_cashflow_taxonomy import classify_cashflow_type

_INSPECTOR_CONSUMER_SYSTEM = "lotus-performance-inspector"
_SAMPLE_LIMIT = 25


def _decimal_to_artifact(value: Decimal) -> str:
    return format(value, "f")


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
    conflicting_explicit_amount_fields: tuple[dict[str, object], ...]
    invalid_explicit_amount_fields: tuple[dict[str, object], ...]
    invalid_cashflow_collection: dict[str, object] | None
    invalid_cashflow_rows: tuple[dict[str, object], ...]
    invalid_amount_rows: tuple[dict[str, object], ...]
    invalid_timing_rows: tuple[dict[str, object], ...]
    missing_cashflow_type_rows: tuple[dict[str, object], ...]
    noncanonical_cashflow_types: tuple[str, ...]
    unsupported_cashflow_type_rows: tuple[dict[str, object], ...]
    governed_alias_cashflow_type_rows: tuple[dict[str, object], ...]
    fee_bod_timing_rows: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class RawObservationEconomics:
    detailed_external_bod: Decimal
    detailed_external_eod: Decimal
    detailed_fee_bod: Decimal
    detailed_fee_eod: Decimal
    explicit_bod_total: Decimal | None
    explicit_eod_total: Decimal | None
    explicit_fee_total: Decimal | None
    conflicting_explicit_amount_fields: tuple[dict[str, object], ...]
    invalid_explicit_amount_fields: tuple[dict[str, object], ...]
    invalid_cashflow_collection: dict[str, object] | None
    invalid_cashflow_rows: tuple[dict[str, object], ...]
    invalid_amount_rows: tuple[dict[str, object], ...]
    invalid_timing_rows: tuple[dict[str, object], ...]
    missing_cashflow_type_rows: tuple[dict[str, object], ...]
    noncanonical_cashflow_types: tuple[str, ...]
    unsupported_cashflow_type_rows: tuple[dict[str, object], ...]
    governed_alias_cashflow_type_rows: tuple[dict[str, object], ...]
    fee_bod_timing_rows: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class DetailedCashFlowEconomics:
    external_bod: Decimal
    external_eod: Decimal
    fee_bod: Decimal
    fee_eod: Decimal
    invalid_cashflow_collection: dict[str, object] | None
    invalid_cashflow_rows: tuple[dict[str, object], ...]
    invalid_amount_rows: tuple[dict[str, object], ...]
    invalid_timing_rows: tuple[dict[str, object], ...]
    missing_cashflow_type_rows: tuple[dict[str, object], ...]
    noncanonical_cashflow_types: tuple[str, ...]
    unsupported_cashflow_type_rows: tuple[dict[str, object], ...]
    governed_alias_cashflow_type_rows: tuple[dict[str, object], ...]
    fee_bod_timing_rows: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class SourceObservationBuildResult:
    source_points: list[ObservationSourceEconomics]
    invalid_observation_date_samples: list[dict[str, object]]


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
        observations=_observations_from_payload(portfolio_payload),
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
    observation_build_result = _build_observation_source_economics(
        observations=observations,
        normalized_by_date=normalized_by_date,
    )
    samples = collect_source_economics_samples(
        source_points=observation_build_result.source_points,
        invalid_observation_date_samples=observation_build_result.invalid_observation_date_samples,
    )

    findings = build_source_economics_findings(
        portfolio_id=portfolio_id,
        samples=samples,
    )

    return SourceEconomicsCheckResult(
        findings=findings,
        evidence_summary=_build_evidence_summary(
            observations=observations,
            samples=samples,
        ),
        artifact_payload=_build_artifact_payload(
            portfolio_id=portfolio_id,
            observations=observations,
            samples=samples,
        ),
    )


def _build_evidence_summary(
    *,
    observations: list[dict[str, object]],
    samples: SourceEconomicsSamples,
) -> dict[str, object]:
    return {
        "portfolio_observation_count": len(observations),
        "invalid_observation_date_count": len(samples.invalid_observation_date_samples),
        "fee_cashflow_date_count": len(samples.fee_flow_dates),
        "external_cashflow_date_count": len(samples.external_flow_dates),
        "fee_normalization_gap_count": len(samples.fee_normalization_samples),
        "duplicate_fee_signal_count": len(samples.duplicate_fee_signal_samples),
        "fee_source_mismatch_count": len(samples.fee_source_mismatch_samples),
        "positive_fee_signal_count": len(samples.positive_fee_signal_samples),
        "fee_timing_bucket_anomaly_count": len(samples.fee_timing_bucket_samples),
        "fee_cashflow_mixed_timing_date_count": len(samples.fee_mixed_timing_samples),
        "external_cashflow_normalization_gap_count": len(samples.external_normalization_samples),
        "duplicate_external_cashflow_signal_count": len(samples.duplicate_external_signal_samples),
        "external_cashflow_source_mismatch_count": len(samples.external_source_mismatch_samples),
        "external_cashflow_timing_contradiction_count": len(samples.external_timing_contradiction_samples),
        "external_cashflow_mixed_timing_date_count": len(samples.external_mixed_timing_samples),
        "external_cashflow_explicit_mixed_timing_date_count": len(samples.external_explicit_mixed_timing_samples),
        "conflicting_explicit_source_amount_date_count": len(samples.conflicting_explicit_amount_samples),
        "invalid_explicit_source_amount_date_count": len(samples.invalid_explicit_amount_samples),
        "invalid_cashflow_collection_date_count": len(samples.invalid_cashflow_collection_samples),
        "invalid_cashflow_row_date_count": len(samples.invalid_cashflow_row_samples),
        "invalid_cashflow_amount_date_count": len(samples.invalid_amount_samples),
        "invalid_cashflow_timing_date_count": len(samples.invalid_timing_samples),
        "missing_cashflow_type_date_count": len(samples.missing_cashflow_type_samples),
        "noncanonical_cashflow_type_date_count": len(samples.noncanonical_cashflow_type_samples),
        "unsupported_cashflow_type_date_count": len(samples.unsupported_cashflow_type_samples),
        "governed_alias_cashflow_type_date_count": len(samples.governed_alias_cashflow_type_samples),
    }


def _build_artifact_payload(
    *,
    portfolio_id: str,
    observations: list[dict[str, object]],
    samples: SourceEconomicsSamples,
) -> dict[str, object]:
    return {
        "portfolio_id": portfolio_id,
        "portfolio_observation_count": len(observations),
        "invalid_observation_date_count": len(samples.invalid_observation_date_samples),
        "invalid_observation_date_samples": samples.invalid_observation_date_samples[:_SAMPLE_LIMIT],
        "fee_cashflow_dates": samples.fee_flow_dates,
        "external_cashflow_dates": samples.external_flow_dates,
        "fee_cashflow_date_count": len(samples.fee_flow_dates),
        "external_cashflow_date_count": len(samples.external_flow_dates),
        "fee_normalization_gap_count": len(samples.fee_normalization_samples),
        "fee_normalization_gap_samples": samples.fee_normalization_samples[:_SAMPLE_LIMIT],
        "duplicate_fee_signal_count": len(samples.duplicate_fee_signal_samples),
        "duplicate_fee_signal_samples": samples.duplicate_fee_signal_samples[:_SAMPLE_LIMIT],
        "fee_source_mismatch_count": len(samples.fee_source_mismatch_samples),
        "fee_source_mismatch_samples": samples.fee_source_mismatch_samples[:_SAMPLE_LIMIT],
        "positive_fee_signal_count": len(samples.positive_fee_signal_samples),
        "positive_fee_signal_samples": samples.positive_fee_signal_samples[:_SAMPLE_LIMIT],
        "fee_timing_bucket_anomaly_count": len(samples.fee_timing_bucket_samples),
        "fee_timing_bucket_samples": samples.fee_timing_bucket_samples[:_SAMPLE_LIMIT],
        "fee_cashflow_mixed_timing_date_count": len(samples.fee_mixed_timing_samples),
        "fee_cashflow_mixed_timing_samples": samples.fee_mixed_timing_samples[:_SAMPLE_LIMIT],
        "external_cashflow_normalization_gap_count": len(samples.external_normalization_samples),
        "external_cashflow_normalization_gap_samples": samples.external_normalization_samples[:_SAMPLE_LIMIT],
        "duplicate_external_cashflow_signal_count": len(samples.duplicate_external_signal_samples),
        "duplicate_external_cashflow_signal_samples": samples.duplicate_external_signal_samples[:_SAMPLE_LIMIT],
        "external_cashflow_source_mismatch_count": len(samples.external_source_mismatch_samples),
        "external_cashflow_source_mismatch_samples": samples.external_source_mismatch_samples[:_SAMPLE_LIMIT],
        "external_cashflow_timing_contradiction_count": len(samples.external_timing_contradiction_samples),
        "external_cashflow_timing_contradiction_samples": (
            samples.external_timing_contradiction_samples[:_SAMPLE_LIMIT]
        ),
        "external_cashflow_mixed_timing_date_count": len(samples.external_mixed_timing_samples),
        "external_cashflow_mixed_timing_samples": samples.external_mixed_timing_samples[:_SAMPLE_LIMIT],
        "external_cashflow_explicit_mixed_timing_date_count": len(samples.external_explicit_mixed_timing_samples),
        "external_cashflow_explicit_mixed_timing_samples": (
            samples.external_explicit_mixed_timing_samples[:_SAMPLE_LIMIT]
        ),
        "conflicting_explicit_source_amount_date_count": len(samples.conflicting_explicit_amount_samples),
        "conflicting_explicit_source_amount_samples": samples.conflicting_explicit_amount_samples[:_SAMPLE_LIMIT],
        "invalid_explicit_source_amount_date_count": len(samples.invalid_explicit_amount_samples),
        "invalid_explicit_source_amount_samples": samples.invalid_explicit_amount_samples[:_SAMPLE_LIMIT],
        "invalid_cashflow_collection_date_count": len(samples.invalid_cashflow_collection_samples),
        "invalid_cashflow_collection_samples": samples.invalid_cashflow_collection_samples[:_SAMPLE_LIMIT],
        "invalid_cashflow_row_date_count": len(samples.invalid_cashflow_row_samples),
        "invalid_cashflow_row_samples": samples.invalid_cashflow_row_samples[:_SAMPLE_LIMIT],
        "invalid_cashflow_amount_date_count": len(samples.invalid_amount_samples),
        "invalid_cashflow_amount_samples": samples.invalid_amount_samples[:_SAMPLE_LIMIT],
        "invalid_cashflow_timing_date_count": len(samples.invalid_timing_samples),
        "invalid_cashflow_timing_samples": samples.invalid_timing_samples[:_SAMPLE_LIMIT],
        "missing_cashflow_type_date_count": len(samples.missing_cashflow_type_samples),
        "missing_cashflow_type_samples": samples.missing_cashflow_type_samples[:_SAMPLE_LIMIT],
        "noncanonical_cashflow_type_date_count": len(samples.noncanonical_cashflow_type_samples),
        "noncanonical_cashflow_type_samples": samples.noncanonical_cashflow_type_samples[:_SAMPLE_LIMIT],
        "noncanonical_cashflow_types": _collect_noncanonical_cashflow_types(samples.noncanonical_cashflow_type_samples),
        "unsupported_cashflow_type_date_count": len(samples.unsupported_cashflow_type_samples),
        "unsupported_cashflow_type_samples": samples.unsupported_cashflow_type_samples[:_SAMPLE_LIMIT],
        "unsupported_cashflow_types": _collect_noncanonical_cashflow_types(samples.unsupported_cashflow_type_samples),
        "governed_alias_cashflow_type_date_count": len(samples.governed_alias_cashflow_type_samples),
        "governed_alias_cashflow_type_samples": samples.governed_alias_cashflow_type_samples[:_SAMPLE_LIMIT],
        "governed_alias_cashflow_types": _collect_noncanonical_cashflow_types(
            samples.governed_alias_cashflow_type_samples
        ),
    }


def _collect_noncanonical_cashflow_types(
    noncanonical_cashflow_type_samples: list[dict[str, object]],
) -> list[str]:
    cashflow_types: set[str] = set()
    for sample in noncanonical_cashflow_type_samples:
        sample_cashflow_types = sample.get("cash_flow_types")
        if not isinstance(sample_cashflow_types, list):
            continue
        cashflow_types.update(
            cash_flow_type for cash_flow_type in sample_cashflow_types if isinstance(cash_flow_type, str)
        )
    return sorted(cashflow_types)


def _observations_from_payload(portfolio_payload: dict[str, object]) -> list[dict[str, object]]:
    observations = portfolio_payload.get("observations", [])
    if not isinstance(observations, list):
        return []
    return [observation for observation in observations if isinstance(observation, dict)]


def _build_observation_source_economics(
    *,
    observations: list[dict[str, object]],
    normalized_by_date: dict[str, dict[str, Decimal]],
) -> SourceObservationBuildResult:
    source_points: list[ObservationSourceEconomics] = []
    invalid_observation_date_samples: list[dict[str, object]] = []
    for observation in observations:
        valuation_date = observation.get("valuation_date")
        if not isinstance(valuation_date, str) or not _is_iso_date(valuation_date):
            invalid_observation_date_samples.append(
                {
                    "valuation_date": valuation_date if isinstance(valuation_date, str) else None,
                    "raw_type": type(valuation_date).__name__,
                    "raw_value": _sample_raw_collection_value(valuation_date),
                    "observation_keys": sorted(str(key) for key in observation),
                }
            )
            continue
        normalized_point = normalized_by_date.get(
            valuation_date,
            {"bod_cf": Decimal("0"), "eod_cf": Decimal("0"), "mgmt_fees": Decimal("0")},
        )
        raw_economics = _collect_observation_economics(observation)
        source_points.append(
            ObservationSourceEconomics(
                valuation_date=valuation_date,
                normalized_bod_cf=normalized_point["bod_cf"],
                normalized_eod_cf=normalized_point["eod_cf"],
                normalized_mgmt_fees=normalized_point["mgmt_fees"],
                detailed_external_bod=raw_economics.detailed_external_bod,
                detailed_external_eod=raw_economics.detailed_external_eod,
                detailed_fee_bod=raw_economics.detailed_fee_bod,
                detailed_fee_eod=raw_economics.detailed_fee_eod,
                explicit_bod_total=raw_economics.explicit_bod_total,
                explicit_eod_total=raw_economics.explicit_eod_total,
                explicit_fee_total=raw_economics.explicit_fee_total,
                conflicting_explicit_amount_fields=raw_economics.conflicting_explicit_amount_fields,
                invalid_explicit_amount_fields=raw_economics.invalid_explicit_amount_fields,
                invalid_cashflow_collection=raw_economics.invalid_cashflow_collection,
                invalid_cashflow_rows=raw_economics.invalid_cashflow_rows,
                invalid_amount_rows=raw_economics.invalid_amount_rows,
                invalid_timing_rows=raw_economics.invalid_timing_rows,
                missing_cashflow_type_rows=raw_economics.missing_cashflow_type_rows,
                noncanonical_cashflow_types=raw_economics.noncanonical_cashflow_types,
                unsupported_cashflow_type_rows=raw_economics.unsupported_cashflow_type_rows,
                governed_alias_cashflow_type_rows=raw_economics.governed_alias_cashflow_type_rows,
                fee_bod_timing_rows=raw_economics.fee_bod_timing_rows,
            )
        )
    return SourceObservationBuildResult(
        source_points=source_points,
        invalid_observation_date_samples=invalid_observation_date_samples,
    )


def _is_iso_date(raw_value: str) -> bool:
    try:
        date.fromisoformat(raw_value)
    except ValueError:
        return False
    return True


def _collect_observation_economics(observation: dict[str, object]) -> RawObservationEconomics:
    detailed_cash_flows = _sum_detailed_cash_flows(observation.get("cash_flows"))
    explicit_bod_total, conflicting_bod_fields, invalid_bod_fields = _read_explicit_decimal_fields(
        observation,
        semantic="bod_cashflow_total",
        keys=("bod_cashflow", "beginning_cash_flow"),
    )
    explicit_eod_total, conflicting_eod_fields, invalid_eod_fields = _read_explicit_decimal_fields(
        observation,
        semantic="eod_cashflow_total",
        keys=("eod_cashflow", "ending_cash_flow"),
    )
    explicit_fee_total, conflicting_fee_fields, invalid_fee_fields = _read_explicit_decimal_fields(
        observation,
        semantic="fee_total",
        keys=("fees", "management_fees"),
    )
    return RawObservationEconomics(
        detailed_external_bod=detailed_cash_flows.external_bod,
        detailed_external_eod=detailed_cash_flows.external_eod,
        detailed_fee_bod=detailed_cash_flows.fee_bod,
        detailed_fee_eod=detailed_cash_flows.fee_eod,
        explicit_bod_total=explicit_bod_total,
        explicit_eod_total=explicit_eod_total,
        explicit_fee_total=explicit_fee_total,
        conflicting_explicit_amount_fields=conflicting_bod_fields + conflicting_eod_fields + conflicting_fee_fields,
        invalid_explicit_amount_fields=invalid_bod_fields + invalid_eod_fields + invalid_fee_fields,
        invalid_cashflow_collection=detailed_cash_flows.invalid_cashflow_collection,
        invalid_cashflow_rows=detailed_cash_flows.invalid_cashflow_rows,
        invalid_amount_rows=detailed_cash_flows.invalid_amount_rows,
        invalid_timing_rows=detailed_cash_flows.invalid_timing_rows,
        missing_cashflow_type_rows=detailed_cash_flows.missing_cashflow_type_rows,
        noncanonical_cashflow_types=detailed_cash_flows.noncanonical_cashflow_types,
        unsupported_cashflow_type_rows=detailed_cash_flows.unsupported_cashflow_type_rows,
        governed_alias_cashflow_type_rows=detailed_cash_flows.governed_alias_cashflow_type_rows,
        fee_bod_timing_rows=detailed_cash_flows.fee_bod_timing_rows,
    )


def _sum_detailed_cash_flows(cash_flows_raw: object) -> DetailedCashFlowEconomics:
    external_bod = Decimal("0")
    external_eod = Decimal("0")
    fee_bod = Decimal("0")
    fee_eod = Decimal("0")
    invalid_cashflow_collection = None
    invalid_cashflow_rows: list[dict[str, object]] = []
    invalid_amount_rows: list[dict[str, object]] = []
    invalid_timing_rows: list[dict[str, object]] = []
    missing_cashflow_type_rows: list[dict[str, object]] = []
    noncanonical_cashflow_types: set[str] = set()
    unsupported_cashflow_type_rows: list[dict[str, object]] = []
    governed_alias_cashflow_type_rows: list[dict[str, object]] = []
    fee_bod_timing_rows: list[dict[str, object]] = []
    if not isinstance(cash_flows_raw, list):
        if cash_flows_raw is not None:
            invalid_cashflow_collection = {
                "raw_type": type(cash_flows_raw).__name__,
                "raw_value": _sample_raw_collection_value(cash_flows_raw),
            }
        return DetailedCashFlowEconomics(
            external_bod=external_bod,
            external_eod=external_eod,
            fee_bod=fee_bod,
            fee_eod=fee_eod,
            invalid_cashflow_collection=invalid_cashflow_collection,
            invalid_cashflow_rows=(),
            invalid_amount_rows=(),
            invalid_timing_rows=(),
            missing_cashflow_type_rows=(),
            noncanonical_cashflow_types=(),
            unsupported_cashflow_type_rows=(),
            governed_alias_cashflow_type_rows=(),
            fee_bod_timing_rows=(),
        )

    for flow in cash_flows_raw:
        if not isinstance(flow, dict):
            invalid_cashflow_rows.append(
                {
                    "raw_type": type(flow).__name__,
                    "raw_value": _sample_raw_collection_value(flow),
                }
            )
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
                    "amount": _decimal_to_artifact(amount),
                    "cash_flow_type": cash_flow_type,
                }
            )
            continue
        cashflow_type_classification = classify_cashflow_type(cash_flow_type)
        normalized_cash_flow_type = cashflow_type_classification.normalized_value
        if cashflow_type_classification.economics_role == "missing":
            missing_cashflow_type_rows.append({"timing": normalized_timing, "amount": _decimal_to_artifact(amount)})
        elif not cashflow_type_classification.canonical:
            if normalized_cash_flow_type is None:
                continue
            noncanonical_cashflow_types.add(normalized_cash_flow_type)
            sample_row = {
                "timing": normalized_timing,
                "amount": _decimal_to_artifact(amount),
                "cash_flow_type": normalized_cash_flow_type,
            }
            if cashflow_type_classification.governed_alias:
                governed_alias_cashflow_type_rows.append(sample_row)
            else:
                unsupported_cashflow_type_rows.append(sample_row)
        if cashflow_type_classification.economics_role == "fee":
            if normalized_timing == "bod":
                fee_bod += amount
                fee_bod_timing_rows.append(
                    {
                        "timing": normalized_timing,
                        "amount": _decimal_to_artifact(amount),
                        "cash_flow_type": normalized_cash_flow_type,
                    }
                )
            else:
                fee_eod += amount
            continue
        if cashflow_type_classification.economics_role == "unsupported":
            continue
        if normalized_timing == "bod":
            external_bod += amount
        else:
            external_eod += amount
    return DetailedCashFlowEconomics(
        external_bod=external_bod,
        external_eod=external_eod,
        fee_bod=fee_bod,
        fee_eod=fee_eod,
        invalid_cashflow_collection=None,
        invalid_cashflow_rows=tuple(invalid_cashflow_rows),
        invalid_amount_rows=tuple(invalid_amount_rows),
        invalid_timing_rows=tuple(invalid_timing_rows),
        missing_cashflow_type_rows=tuple(missing_cashflow_type_rows),
        noncanonical_cashflow_types=tuple(sorted(noncanonical_cashflow_types)),
        unsupported_cashflow_type_rows=tuple(unsupported_cashflow_type_rows),
        governed_alias_cashflow_type_rows=tuple(governed_alias_cashflow_type_rows),
        fee_bod_timing_rows=tuple(fee_bod_timing_rows),
    )


def _read_explicit_decimal_fields(
    observation: dict[str, object],
    *,
    semantic: str,
    keys: tuple[str, ...],
) -> tuple[Decimal | None, tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    decimal_value: Decimal | None = None
    decimal_field: str | None = None
    conflicting_fields: list[dict[str, object]] = []
    invalid_fields: list[dict[str, object]] = []
    for key in keys:
        raw_value = observation.get(key)
        if raw_value is None:
            continue
        parsed_value = _parse_decimal(raw_value)
        if parsed_value is not None:
            if decimal_value is None:
                decimal_value = parsed_value
                decimal_field = key
            elif not _decimals_match(decimal_value, parsed_value):
                conflicting_fields.append(
                    {
                        "field": key,
                        "semantic": semantic,
                        "raw_value": raw_value,
                        "resolved_field": decimal_field,
                        "resolved_value": _decimal_to_artifact(decimal_value),
                        "conflicting_value": _decimal_to_artifact(parsed_value),
                    }
                )
            continue
        invalid_fields.append({"field": key, "semantic": semantic, "raw_value": raw_value})
    return decimal_value, tuple(conflicting_fields), tuple(invalid_fields)


def _sample_raw_collection_value(raw_value: object) -> object:
    if isinstance(raw_value, str | bool) or raw_value is None:
        return raw_value
    if isinstance(raw_value, Real):
        return raw_value
    if isinstance(raw_value, dict):
        return raw_value
    return repr(raw_value)


def _decimals_match(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= Decimal("0.01")


def _parse_decimal(raw_value: object) -> Decimal | None:
    if raw_value is None:
        return None
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        return None
