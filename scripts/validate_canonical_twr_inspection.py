from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PORTFOLIO_ID = "PB_SG_GLOBAL_BAL_001"
DEFAULT_AS_OF_DATE = "2026-04-10"
DEFAULT_PERFORMANCE_BASE_URL = "http://127.0.0.1:8002"
DEFAULT_CORE_CONTROL_PLANE_BASE_URL = "http://127.0.0.1:8202"
DEFAULT_ALLOWED_FINDING_CODES = ("WEEKEND_OBSERVATIONS_PRESENT",)

REQUIRED_ZERO_EVIDENCE_FIELDS = (
    "nonpositive_capital_base_count",
    "reconciliation_gap_date_count",
    "external_cashflow_normalization_gap_count",
    "external_cashflow_timing_contradiction_count",
    "noncanonical_cashflow_type_date_count",
    "unsupported_cashflow_type_date_count",
)

REQUIRED_CONTROL_PLANE_ROUTES = (
    "analytics/reference",
    "analytics/portfolio-timeseries",
    "analytics/position-timeseries",
)


@dataclass(frozen=True)
class CanonicalTWRInspectionValidation:
    passed: bool
    errors: list[str]
    summary: dict[str, Any]


def validate_canonical_inspection_summary(
    inspection_summary: dict[str, Any],
    *,
    allowed_finding_codes: tuple[str, ...] = DEFAULT_ALLOWED_FINDING_CODES,
) -> CanonicalTWRInspectionValidation:
    errors: list[str] = []
    evidence_summary = _as_dict(inspection_summary.get("evidence_summary"))
    finding_codes = [
        str(finding.get("code"))
        for finding in _as_list(inspection_summary.get("findings"))
        if isinstance(finding, dict) and finding.get("code")
    ]

    for field_name in REQUIRED_ZERO_EVIDENCE_FIELDS:
        if _as_int(evidence_summary.get(field_name)) != 0:
            errors.append(f"{field_name} expected 0, got {evidence_summary.get(field_name)!r}")

    disallowed_findings = sorted(set(finding_codes) - set(allowed_finding_codes))
    if disallowed_findings:
        errors.append(f"disallowed finding codes present: {', '.join(disallowed_findings)}")

    completed_check_families = _as_dict(inspection_summary.get("check_coverage")).get("completed_check_families", [])
    required_families = {
        "calculation_consistency",
        "source_quality",
        "economic_plausibility",
        "reconciliation",
        "cashflow_classification",
    }
    missing_families = sorted(required_families - set(str(item) for item in _as_list(completed_check_families)))
    if missing_families:
        errors.append(f"missing completed check families: {', '.join(missing_families)}")

    if _as_dict(inspection_summary.get("check_coverage")).get("pending_check_families"):
        errors.append("pending check families are present")
    if _as_dict(inspection_summary.get("check_coverage")).get("failed_check_families"):
        errors.append("failed check families are present")

    summary = {
        "inspection_id": inspection_summary.get("inspection_id"),
        "subject_calculation_id": inspection_summary.get("subject_calculation_id"),
        "verdict": inspection_summary.get("verdict"),
        "finding_codes": finding_codes,
        "allowed_finding_codes": list(allowed_finding_codes),
        "evidence_summary": {
            field_name: evidence_summary.get(field_name) for field_name in REQUIRED_ZERO_EVIDENCE_FIELDS
        }
        | {
            "fee_cashflow_date_count": evidence_summary.get("fee_cashflow_date_count"),
            "external_cashflow_date_count": evidence_summary.get("external_cashflow_date_count"),
            "largest_abs_daily_move_pct": evidence_summary.get("largest_abs_daily_move_pct"),
            "reconciliation_max_gap_amount": evidence_summary.get("reconciliation_max_gap_amount"),
            "weekend_observation_count": evidence_summary.get("weekend_observation_count"),
        },
    }
    return CanonicalTWRInspectionValidation(
        passed=not errors,
        errors=errors,
        summary=summary,
    )


def run_live_validation(
    *,
    performance_base_url: str,
    core_control_plane_base_url: str,
    portfolio_id: str,
    as_of_date: str,
    allowed_finding_codes: tuple[str, ...],
    timeout_seconds: int,
) -> CanonicalTWRInspectionValidation:
    _probe_core_control_plane(
        core_control_plane_base_url=core_control_plane_base_url,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        timeout_seconds=timeout_seconds,
    )
    twr_response = _post_json(
        f"{performance_base_url.rstrip('/')}/performance/twr",
        {
            "portfolio_id": portfolio_id,
            "input_mode": "stateful",
            "stateful_input": {},
            "metric_basis": "NET",
            "report_end_date": as_of_date,
            "report_ccy": "USD",
            "include_benchmark": False,
            "analyses": [{"period": "YTD", "frequencies": ["daily", "monthly"]}],
            "output": {"include_timeseries": True},
        },
        timeout_seconds=timeout_seconds,
    )
    twr_result = _resolve_twr_result(
        performance_base_url=performance_base_url,
        twr_response=twr_response,
        timeout_seconds=timeout_seconds,
    )
    inspection = _post_json(
        f"{performance_base_url.rstrip('/')}/performance/inspections/twr",
        {
            "subject_type": "twr_calculation",
            "subject_calculation_id": twr_result["calculation_id"],
            "inspection_profile": "canonical_validation",
        },
        timeout_seconds=timeout_seconds,
    )
    inspection_result = _poll_json(
        f"{performance_base_url.rstrip('/')}{inspection['result_path']}",
        timeout_seconds=timeout_seconds,
    )
    validation = validate_canonical_inspection_summary(
        inspection_result,
        allowed_finding_codes=allowed_finding_codes,
    )
    validation.summary["twr"] = {
        "calculation_id": twr_result.get("calculation_id"),
        "input_mode": twr_result.get("input_mode"),
        "periods": _as_dict(twr_result.get("meta")).get("periods"),
        "ytd_summary": _as_dict(_as_dict(twr_result.get("results_by_period")).get("YTD"))
        .get("portfolio", {})
        .get("summary"),
    }
    return validation


def _probe_core_control_plane(
    *,
    core_control_plane_base_url: str,
    portfolio_id: str,
    as_of_date: str,
    timeout_seconds: int,
) -> None:
    base_url = core_control_plane_base_url.rstrip()
    route_payloads = {
        "analytics/reference": {"as_of_date": as_of_date},
        "analytics/portfolio-timeseries": _timeseries_payload(as_of_date),
        "analytics/position-timeseries": _timeseries_payload(as_of_date)
        | {"dimensions": [], "include_cash_flows": True, "filters": {}},
    }
    for route in REQUIRED_CONTROL_PLANE_ROUTES:
        _post_json(
            f"{base_url}/integration/portfolios/{portfolio_id}/{route}",
            route_payloads[route],
            timeout_seconds=timeout_seconds,
        )


def _timeseries_payload(as_of_date: str) -> dict[str, Any]:
    return {
        "as_of_date": as_of_date,
        "window": {"start_date": "2026-01-01", "end_date": as_of_date},
        "frequency": "daily",
        "consumer_system": "lotus-performance-canonical-validator",
        "page": {"page_size": 5000, "page_token": None},
        "reporting_currency": "USD",
    }


def _resolve_twr_result(
    *,
    performance_base_url: str,
    twr_response: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    if twr_response.get("result_path"):
        return _poll_json(
            f"{performance_base_url.rstrip('/')}{twr_response['result_path']}",
            timeout_seconds=timeout_seconds,
            is_complete=lambda payload: bool(payload.get("results_by_period")),
        )
    return twr_response


def _poll_json(
    url: str,
    *,
    timeout_seconds: int,
    is_complete: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        payload = _get_json(url, timeout_seconds=min(10, timeout_seconds))
        last_payload = payload
        if is_complete is not None and is_complete(payload):
            return payload
        if is_complete is None and payload.get("status") == "complete":
            return payload
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for {url}; last payload={last_payload}")


def _post_json(url: str, payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _send_json(request, timeout_seconds=timeout_seconds)


def _get_json(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    return _send_json(Request(url, method="GET"), timeout_seconds=timeout_seconds)


def _send_json(request: Request, *, timeout_seconds: int) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{request.full_url} failed with {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"{request.full_url} unavailable: {exc.reason}") from exc


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return -1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate canonical stateful TWR and RFC-045 inspection evidence against live local Lotus services."
    )
    parser.add_argument("--performance-base-url", default=DEFAULT_PERFORMANCE_BASE_URL)
    parser.add_argument("--core-control-plane-base-url", default=DEFAULT_CORE_CONTROL_PLANE_BASE_URL)
    parser.add_argument("--portfolio-id", default=DEFAULT_PORTFOLIO_ID)
    parser.add_argument("--as-of-date", default=DEFAULT_AS_OF_DATE)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--allowed-finding-code",
        action="append",
        default=list(DEFAULT_ALLOWED_FINDING_CODES),
        help="Finding code allowed during canonical validation. Repeat to allow more than one.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    validation = run_live_validation(
        performance_base_url=args.performance_base_url,
        core_control_plane_base_url=args.core_control_plane_base_url,
        portfolio_id=args.portfolio_id,
        as_of_date=args.as_of_date,
        allowed_finding_codes=tuple(args.allowed_finding_code),
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(validation.summary, indent=2, sort_keys=True))
    if validation.passed:
        return 0
    print("Canonical TWR inspection validation failed:", file=sys.stderr)
    for error in validation.errors:
        print(f"- {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
