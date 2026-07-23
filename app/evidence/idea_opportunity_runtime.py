from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.models.returns_series import InputMode, ReturnsSeriesRequest, ReturnsSeriesResponse
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_RETURNS_SERIES
from app.services.execution_registry import execution_registry
from app.services.returns_series_service import calculate_returns_series

SCHEMA_VERSION = "lotus-performance.idea-opportunity-runtime-evidence.v1"
PRODUCT_ID = "lotus-performance:ReturnsSeriesBundle:v1"
PROOF_FAMILY = "idea_opportunity_archetype_source_evidence"
RUNTIME_BOUNDARY = "lotus-performance:returns-series-runtime"
RFC_ID = "RFC-0002"
RFC_SLICES = ("slice-16", "slice-17")

UNDERPERFORMANCE_SCENARIO_ID = "underperformance_review_returns_series"
MISSING_BENCHMARK_SCENARIO_ID = "missing_benchmark_performance_readiness"

IDEA_BLOCKERS_CLEARED = (
    "opportunity_archetype_underperformance_live_performance_source_proof_missing",
    "opportunity_archetype_missing_benchmark_performance_readiness_source_proof_missing",
)

IDEA_BLOCKERS_PRESERVED = (
    "core_benchmark_assignment_source_authority_missing",
    "idea_candidate_persistence_runtime_proof_missing",
    "gateway_runtime_consumption_proof_missing",
    "workbench_runtime_consumption_proof_missing",
    "data_mesh_certification_missing",
    "client_publication_runtime_proof_missing",
    "supported_feature_promotion_missing",
)

FORBIDDEN_RAW_VALUES = (
    "PB_SG_GLOBAL_BAL_001",
    "CLIENT_",
    "ACCOUNT_",
    "HOLDING_",
)

FORBIDDEN_SCENARIO_KEYS = {
    "series",
    "portfolio_returns",
    "benchmark_returns",
    "risk_free_returns",
    "cumulative_portfolio_returns",
    "cumulative_benchmark_returns",
    "cumulative_active_returns",
    "active_returns",
}


def default_output_path() -> str:
    return "output/idea-opportunity-runtime-evidence/latest.json"


async def generate_idea_opportunity_runtime_evidence(
    *,
    portfolio_id: str = "PB_SG_GLOBAL_BAL_001",
    benchmark_id: str = "BMK_GLOBAL_60_40_USD",
    as_of_date: date = date(2026, 5, 8),
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or datetime.now(tz=UTC)
    execution_registry.create_schema()
    underperformance_request = _underperformance_request(portfolio_id=portfolio_id, as_of_date=as_of_date)
    _seed_sync_execution(underperformance_request)
    underperformance_response = await calculate_returns_series(
        underperformance_request,
        source_input_mode=InputMode.STATELESS,
        resolved_benchmark_id_override=benchmark_id,
        resolved_benchmark_return_source_override=BenchmarkReturnSource.CALCULATED.value,
    )

    missing_benchmark_request = _missing_benchmark_request(portfolio_id=portfolio_id, as_of_date=as_of_date)
    _seed_sync_execution(missing_benchmark_request)
    missing_benchmark_response = await calculate_returns_series(
        missing_benchmark_request,
        source_input_mode=InputMode.STATELESS,
    )

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "proof_family": PROOF_FAMILY,
        "runtime_boundary": RUNTIME_BOUNDARY,
        "product_id": PRODUCT_ID,
        "source_authority": {
            "service": "lotus-performance",
            "owned_contract": PRODUCT_ID,
            "source_methodology": "performance-owned returns-series calculation, coverage, freshness, and benchmark-context evidence",
            "downstream_authority_boundary": (
                "lotus-idea may consume source refs and proof status, but must not calculate official "
                "performance, benchmark, active-return, or benchmark-readiness values."
            ),
        },
        "rfc": {"id": RFC_ID, "slices": list(RFC_SLICES)},
        "generated_at_utc": generated_at.isoformat().replace("+00:00", "Z"),
        "portfolio_identity": {
            "identity_digest": _identity_digest("portfolio", portfolio_id),
            "source_identity_class": "canonical_front_office_portfolio",
            "raw_identifier_policy": "not_emitted",
        },
        "scenarios": [
            _scenario_evidence(
                scenario_id=UNDERPERFORMANCE_SCENARIO_ID,
                opportunity_archetype="underperformance_review",
                request=underperformance_request,
                response=underperformance_response,
                benchmark_id=benchmark_id,
                expected_benchmark_context_state="resolved",
            ),
            _scenario_evidence(
                scenario_id=MISSING_BENCHMARK_SCENARIO_ID,
                opportunity_archetype="missing_benchmark_review",
                request=missing_benchmark_request,
                response=missing_benchmark_response,
                benchmark_id=None,
                expected_benchmark_context_state="missing",
            ),
        ],
        "idea_blockers_cleared": list(IDEA_BLOCKERS_CLEARED),
        "idea_blockers_preserved": list(IDEA_BLOCKERS_PRESERVED),
        "unsupported_promotion_policy": {
            "supported_feature_promotion": "not_claimed",
            "deployment_certification": "not_claimed",
            "client_publication": "not_claimed",
        },
    }
    validate_idea_opportunity_runtime_evidence(evidence)
    return evidence


def validate_idea_opportunity_runtime_evidence(evidence: dict[str, Any]) -> None:
    _assert_evidence_schema(evidence)
    _assert_no_forbidden_raw_values(evidence)
    scenario_by_id = _scenario_by_id(evidence)
    _assert_bounded_scenario_payloads(list(scenario_by_id.values()))
    _assert_underperformance_scenario(scenario_by_id[UNDERPERFORMANCE_SCENARIO_ID])
    _assert_missing_benchmark_scenario(scenario_by_id[MISSING_BENCHMARK_SCENARIO_ID])
    _assert_supported_feature_blocker_preserved(evidence)


def _assert_evidence_schema(evidence: dict[str, Any]) -> None:
    if evidence.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported evidence schema: {evidence.get('schema_version')!r}")
    if evidence.get("product_id") != PRODUCT_ID:
        raise ValueError("evidence must be bound to ReturnsSeriesBundle:v1")


def _scenario_by_id(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scenarios = evidence.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 2:
        raise ValueError("evidence must contain exactly two Idea opportunity scenarios")
    scenario_by_id = {
        scenario["scenario_id"]: scenario
        for scenario in scenarios
        if isinstance(scenario, dict) and isinstance(scenario.get("scenario_id"), str)
    }
    required = {UNDERPERFORMANCE_SCENARIO_ID, MISSING_BENCHMARK_SCENARIO_ID}
    if set(scenario_by_id) != required:
        raise ValueError(f"evidence scenarios must be {sorted(required)}")
    return scenario_by_id


def _assert_supported_feature_blocker_preserved(evidence: dict[str, Any]) -> None:
    preserved = set(evidence.get("idea_blockers_preserved") or [])
    if "supported_feature_promotion_missing" not in preserved:
        raise ValueError("evidence must preserve supported-feature promotion blocker")


def _scenario_evidence(
    *,
    scenario_id: str,
    opportunity_archetype: str,
    request: ReturnsSeriesRequest,
    response: ReturnsSeriesResponse,
    benchmark_id: str | None,
    expected_benchmark_context_state: str,
) -> dict[str, Any]:
    request_payload = request.model_dump(mode="json")
    response_payload = response.model_dump(mode="json")
    coverage = response.diagnostics.coverage.model_dump(mode="json")
    benchmark_context = response.benchmark_context.model_dump(mode="json") if response.benchmark_context else None
    benchmark_context_state = "resolved" if benchmark_context else "missing"
    if benchmark_context_state != expected_benchmark_context_state:
        raise ValueError(f"{scenario_id} benchmark context was {benchmark_context_state}")

    return {
        "scenario_id": scenario_id,
        "opportunity_archetype": opportunity_archetype,
        "product_id": PRODUCT_ID,
        "contract_version": response.contract_version,
        "execution_receipt": {
            "calculation_id": str(response.calculation_id),
            "input_mode": response.provenance.input_mode.value,
            "input_fingerprint": response.provenance.input_fingerprint,
            "calculation_hash": response.provenance.calculation_hash,
            "response_contract_version": response.contract_version,
            "source_service": response.source_service,
        },
        "identity": {
            "portfolio_identity_digest": _identity_digest("portfolio", response.portfolio_id),
            "benchmark_identity_digest": _identity_digest("benchmark", benchmark_id) if benchmark_id else None,
            "as_of_date": response.as_of_date.isoformat(),
            "resolved_window": response.resolved_window.model_dump(mode="json"),
            "source_system_id": "lotus-performance",
            "source_revision": _json_digest(request_payload),
        },
        "runtime_digests": {
            "request_digest": _json_digest(request_payload),
            "response_digest": _json_digest(response_payload),
            "source_payload_visibility": "digests_and_bounded_summaries_only",
        },
        "readiness": {
            "supportability_state": _supportability_state(response),
            "freshness": response.diagnostics.freshness,
            "coverage": coverage,
            "gap_count": len(response.diagnostics.gaps),
            "warning_count": len(response.diagnostics.warnings),
            "benchmark_context_state": benchmark_context_state,
            "benchmark_context": benchmark_context,
            "quality_state": _quality_state(response),
            "reason_codes": _reason_codes(response=response, benchmark_context_state=benchmark_context_state),
        },
        "metric_summary": _metric_summary(response),
    }


def _supportability_state(response: ReturnsSeriesResponse) -> str:
    diagnostics = response.diagnostics
    if diagnostics.freshness != "current":
        return "degraded"
    if diagnostics.coverage.missing_points > 0:
        return "degraded"
    if diagnostics.warnings:
        return "degraded"
    return "ready"


def _quality_state(response: ReturnsSeriesResponse) -> str:
    if _supportability_state(response) == "ready":
        return "source_ready"
    return "source_degraded"


def _reason_codes(*, response: ReturnsSeriesResponse, benchmark_context_state: str) -> list[str]:
    reason_codes: list[str] = []
    if response.diagnostics.freshness != "current":
        reason_codes.append("RETURNS_SERIES_FRESHNESS_STALE")
    if response.diagnostics.coverage.missing_points > 0:
        reason_codes.append("RETURNS_SERIES_COVERAGE_PARTIAL")
    if response.diagnostics.warnings:
        reason_codes.append("RETURNS_SERIES_WARNINGS_PRESENT")
    if benchmark_context_state == "missing":
        reason_codes.append("BENCHMARK_CONTEXT_MISSING")
    if not reason_codes:
        reason_codes.append("RETURNS_SERIES_SOURCE_READY")
    return reason_codes


def _metric_summary(response: ReturnsSeriesResponse) -> dict[str, Any]:
    active_returns = response.series.active_returns or []
    cumulative_active_returns = response.series.cumulative_active_returns or []
    last_cumulative_active_return = cumulative_active_returns[-1].return_value if cumulative_active_returns else None
    return {
        "portfolio_points": len(response.series.portfolio_returns),
        "benchmark_points": len(response.series.benchmark_returns or []),
        "active_return_points": len(active_returns),
        "last_cumulative_active_return": str(last_cumulative_active_return) if last_cumulative_active_return else None,
        "active_return_posture": _active_return_posture(last_cumulative_active_return),
    }


def _active_return_posture(value: Decimal | None) -> str:
    if value is None:
        return "not_applicable"
    if value < Decimal("0"):
        return "underperforming"
    if value > Decimal("0"):
        return "outperforming"
    return "flat"


def _underperformance_request(*, portfolio_id: str, as_of_date: date) -> ReturnsSeriesRequest:
    return ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": portfolio_id,
            "as_of_date": as_of_date.isoformat(),
            "window": {"mode": "EXPLICIT", "from_date": "2026-05-04", "to_date": "2026-05-08"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "reporting_currency": "USD",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
            "data_policy": {"missing_data_policy": "FAIL_FAST", "fill_method": "NONE", "calendar_policy": "BUSINESS"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-05-04", "return_value": "0.0008"},
                    {"date": "2026-05-05", "return_value": "-0.0015"},
                    {"date": "2026-05-06", "return_value": "0.0004"},
                    {"date": "2026-05-07", "return_value": "-0.0012"},
                    {"date": "2026-05-08", "return_value": "0.0001"},
                ],
                "benchmark_returns": [
                    {"date": "2026-05-04", "return_value": "0.0016"},
                    {"date": "2026-05-05", "return_value": "0.0007"},
                    {"date": "2026-05-06", "return_value": "0.0011"},
                    {"date": "2026-05-07", "return_value": "0.0006"},
                    {"date": "2026-05-08", "return_value": "0.0009"},
                ],
            },
        }
    )


def _missing_benchmark_request(*, portfolio_id: str, as_of_date: date) -> ReturnsSeriesRequest:
    return ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": portfolio_id,
            "as_of_date": as_of_date.isoformat(),
            "window": {"mode": "EXPLICIT", "from_date": "2026-05-04", "to_date": "2026-05-08"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "reporting_currency": "USD",
            "series_selection": {"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
            "data_policy": {"missing_data_policy": "FAIL_FAST", "fill_method": "NONE", "calendar_policy": "BUSINESS"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-05-04", "return_value": "0.0008"},
                    {"date": "2026-05-05", "return_value": "-0.0015"},
                    {"date": "2026-05-06", "return_value": "0.0004"},
                    {"date": "2026-05-07", "return_value": "-0.0012"},
                    {"date": "2026-05-08", "return_value": "0.0001"},
                ],
            },
        }
    )


def _seed_sync_execution(request: ReturnsSeriesRequest) -> None:
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id=request.portfolio_id,
        execution_mode="sync",
        requested_window={
            "mode": request.window.mode.value,
            "from_date": request.window.from_date.isoformat() if request.window.from_date else None,
            "to_date": request.window.to_date.isoformat() if request.window.to_date else None,
            "input_mode": request.input_mode.value,
            "proof_family": PROOF_FAMILY,
        },
    )


def _json_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _identity_digest(kind: str, identifier: str | None) -> str | None:
    if identifier is None:
        return None
    return _json_digest({"kind": kind, "identifier": identifier})


def _assert_no_forbidden_raw_values(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, default=str)
    for raw_value in FORBIDDEN_RAW_VALUES:
        if raw_value in encoded:
            raise ValueError(f"source-safe evidence must not emit raw value {raw_value!r}")


def _assert_bounded_scenario_payloads(scenarios: list[dict[str, Any]]) -> None:
    for scenario in scenarios:
        _assert_no_forbidden_scenario_key(scenario)


def _assert_no_forbidden_scenario_key(payload: Any) -> None:
    if isinstance(payload, dict):
        overlap = FORBIDDEN_SCENARIO_KEYS.intersection(payload)
        if overlap:
            raise ValueError(f"scenario evidence contains raw return-series keys: {sorted(overlap)}")
        for value in payload.values():
            _assert_no_forbidden_scenario_key(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_forbidden_scenario_key(value)


def _assert_underperformance_scenario(scenario: dict[str, Any]) -> None:
    readiness = scenario.get("readiness")
    if not isinstance(readiness, dict):
        raise ValueError("underperformance scenario readiness is missing")
    if readiness.get("benchmark_context_state") != "resolved":
        raise ValueError("underperformance scenario must have resolved benchmark context")
    metric_summary = scenario.get("metric_summary")
    if not isinstance(metric_summary, dict) or metric_summary.get("active_return_posture") != "underperforming":
        raise ValueError("underperformance scenario must prove underperforming active-return posture")
    if readiness.get("supportability_state") != "ready":
        raise ValueError("underperformance scenario must be source-ready")


def _assert_missing_benchmark_scenario(scenario: dict[str, Any]) -> None:
    readiness = scenario.get("readiness")
    if not isinstance(readiness, dict):
        raise ValueError("missing-benchmark scenario readiness is missing")
    if readiness.get("benchmark_context_state") != "missing":
        raise ValueError("missing-benchmark scenario must preserve missing benchmark context")
    reason_codes = readiness.get("reason_codes")
    if not isinstance(reason_codes, list) or "BENCHMARK_CONTEXT_MISSING" not in reason_codes:
        raise ValueError("missing-benchmark scenario must carry BENCHMARK_CONTEXT_MISSING")
    if readiness.get("freshness") != "current":
        raise ValueError("missing-benchmark scenario must preserve current portfolio freshness")


def copy_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(evidence)
