from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXPECTED_READY_CUMULATIVE_RETURN = Decimal("0.045500000000")
EXPECTED_DEGRADED_RETURN = Decimal("0.010000000000")
REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ProbeResult:
    name: str
    url: str
    status_code: int
    response_headers: dict[str, str]
    payload: dict[str, Any]


def _post_json(url: str, payload: dict[str, Any], *, correlation_id: str) -> ProbeResult:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Correlation-Id": correlation_id,
            "X-Actor-Id": "rfc-049-live-proof-agent",
            "X-Caller-Application": "lotus-performance-rfc-049-live-proof",
            "X-Tenant-Id": "private-bank-demo",
            "X-Region": "SG",
            "X-Booking-Center-Code": "SG",
            "X-Role": "performance-operator",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response_body = response.read().decode("utf-8")
            return ProbeResult(
                name="",
                url=url,
                status_code=response.status,
                response_headers=dict(response.headers.items()),
                payload=json.loads(response_body),
            )
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8")
        return ProbeResult(
            name="",
            url=url,
            status_code=exc.code,
            response_headers=dict(exc.headers.items()),
            payload=json.loads(response_body),
        )
    except URLError as exc:
        raise RuntimeError(f"Unable to call {url}: {exc}") from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _data_payload(result: ProbeResult) -> dict[str, Any]:
    if "data" in result.payload and isinstance(result.payload["data"], dict):
        return result.payload["data"]
    return result.payload


def _assert_decimal(actual: str | None, expected: Decimal, label: str) -> None:
    if actual is None:
        raise AssertionError(f"{label} was null; expected {expected}")
    if Decimal(actual) != expected:
        raise AssertionError(f"{label} was {actual}; expected {expected}")


def _validate_ready_twr(result: ProbeResult) -> list[str]:
    payload = _data_payload(result)
    checks: list[str] = []
    if result.status_code != 200:
        raise AssertionError(f"{result.name} returned {result.status_code}; expected 200")
    if payload["status"] != "READY":
        raise AssertionError(f"{result.name} status was {payload['status']}; expected READY")
    if payload["methodology"] != "persisted_member_return_asset_weighted_twr_v1":
        raise AssertionError(f"{result.name} methodology drifted: {payload['methodology']}")
    _assert_decimal(payload["cumulative_return"], EXPECTED_READY_CUMULATIVE_RETURN, f"{result.name} cumulative_return")
    checks.append(f"{result.name}: cumulative_return=0.045500000000")

    periods = payload["periods"]
    if len(periods) != 2:
        raise AssertionError(f"{result.name} returned {len(periods)} periods; expected 2")

    first, second = periods
    _assert_decimal(first["return_value"], Decimal("0.025000000000"), f"{result.name} period 1 return")
    _assert_decimal(second["return_value"], Decimal("0.020000000000"), f"{result.name} period 2 return")
    _assert_decimal(first["member_contributions"][0]["beginning_asset_weight"], Decimal("0.250000000000"), "P1 weight")
    _assert_decimal(first["member_contributions"][1]["beginning_asset_weight"], Decimal("0.750000000000"), "P2 weight")
    _assert_decimal(
        second["member_contributions"][0]["beginning_asset_weight"], Decimal("0.250000000000"), "P1 period 2 weight"
    )
    _assert_decimal(
        second["member_contributions"][1]["beginning_asset_weight"], Decimal("0.750000000000"), "P2 period 2 weight"
    )
    if first["excluded_member_count"] != 0 or second["excluded_member_count"] != 0:
        raise AssertionError(f"{result.name} ready fixture unexpectedly excluded members")
    if first["return_view"] != "NET_ACTUAL" or second["return_view"] != "NET_ACTUAL":
        raise AssertionError(f"{result.name} return_view drifted")
    if first["reporting_currency"] != "USD" or second["reporting_currency"] != "USD":
        raise AssertionError(f"{result.name} reporting currency drifted")
    checks.append(f"{result.name}: period returns, weights, currency, return view, and member inclusion verified")
    return checks


def _validate_degraded_twr(result: ProbeResult) -> list[str]:
    payload = _data_payload(result)
    checks: list[str] = []
    if result.status_code != 200:
        raise AssertionError(f"{result.name} returned {result.status_code}; expected 200")
    if payload["status"] != "DEGRADED":
        raise AssertionError(f"{result.name} status was {payload['status']}; expected DEGRADED")
    if payload["reason_codes"] != ["missing_final_valuation"]:
        raise AssertionError(f"{result.name} reason_codes were {payload['reason_codes']}")
    _assert_decimal(payload["cumulative_return"], EXPECTED_DEGRADED_RETURN, f"{result.name} cumulative_return")
    period = payload["periods"][0]
    if period["member_count"] != 1 or period["excluded_member_count"] != 1:
        raise AssertionError(f"{result.name} expected one included and one excluded member")
    checks.append(f"{result.name}: degraded status, reason code, exclusion count, and usable member return verified")
    return checks


def _validate_inspection(result: ProbeResult) -> list[str]:
    payload = _data_payload(result)
    checks: list[str] = []
    if result.status_code != 200:
        raise AssertionError(f"{result.name} returned {result.status_code}; expected 200")
    if payload["verdict"] != "supportable":
        raise AssertionError(f"{result.name} verdict was {payload['verdict']}; expected supportable")
    artifacts = {artifact["artifact_name"]: artifact for artifact in payload["artifacts"]}
    required_artifacts = {
        "member_inputs.csv": "operator_only",
        "period_weights.csv": "operator_only",
        "composite_returns.csv": "customer_consumable",
        "lineage_manifest.json": "operator_only",
        "support_brief.md": "operator_only",
    }
    for artifact_name, access_classification in required_artifacts.items():
        artifact = artifacts.get(artifact_name)
        if artifact is None:
            raise AssertionError(f"{result.name} missing artifact {artifact_name}")
        if artifact["access_classification"] != access_classification:
            raise AssertionError(
                f"{result.name} artifact {artifact_name} had access {artifact['access_classification']}"
            )
    composite_returns = list(csv.DictReader(artifacts["composite_returns.csv"]["artifact_content"].splitlines()))
    if len(composite_returns) != 2:
        raise AssertionError(f"{result.name} composite_returns.csv row count drifted")
    if composite_returns[-1]["cumulative_return"] != str(EXPECTED_READY_CUMULATIVE_RETURN):
        raise AssertionError(f"{result.name} composite_returns.csv cumulative return mismatch")
    checks.append(f"{result.name}: verdict and classified artifacts verified")
    return checks


def _validate_no_facts(result: ProbeResult) -> list[str]:
    payload = result.payload
    if "detail" in payload:
        detail = payload["detail"]
    else:
        detail = payload
    if result.status_code not in {400, 422}:
        raise AssertionError(f"{result.name} returned {result.status_code}; expected 400 or 422")
    serialized = json.dumps(detail, sort_keys=True)
    if "NO_MEMBER_RETURN_FACTS" not in serialized:
        raise AssertionError(f"{result.name} did not preserve NO_MEMBER_RETURN_FACTS: {serialized}")
    return [f"{result.name}: no-facts error contract verified with status {result.status_code}"]


def _probe(
    *,
    name: str,
    base_url: str,
    path: str,
    payload: dict[str, Any],
    correlation_id: str,
    output_dir: Path,
) -> ProbeResult:
    result = _post_json(f"{base_url.rstrip('/')}{path}", payload, correlation_id=correlation_id)
    result = ProbeResult(
        name=name,
        url=result.url,
        status_code=result.status_code,
        response_headers=result.response_headers,
        payload=result.payload,
    )
    _write_json(
        output_dir / f"{name}.json",
        {
            "url": result.url,
            "status_code": result.status_code,
            "response_headers": result.response_headers,
            "payload": result.payload,
        },
    )
    return result


def capture_live_proof(
    *,
    output_dir: Path,
    performance_base_url: str,
    gateway_base_url: str,
    workbench_base_url: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    twr_payload = {
        "calculation_id": "7f2b08b0-58e5-49be-b3ef-7a9cfb0321ce",
        "composite_id": "PB_GLOBAL_BALANCED_USD",
        "period_start": "2026-01-01",
        "period_end": "2026-02-28",
    }
    inspection_payload = {
        "inspection_id": "8d1e37d2-aeca-488c-bd43-77dbf6739103",
        "composite_id": "PB_GLOBAL_BALANCED_USD",
        "period_start": "2026-01-01",
        "period_end": "2026-02-28",
    }
    degraded_payload = {
        "calculation_id": "2a3d9793-77f1-451b-af96-1634279b0cbd",
        "composite_id": "PB_GLOBAL_BALANCED_USD_DEGRADED",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
    }
    no_facts_payload = {
        "calculation_id": "8b7c8cb4-87e9-43d7-bd02-6f3d996f1c21",
        "composite_id": "PB_GLOBAL_BALANCED_USD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
    }

    probes = [
        _probe(
            name="performance-ready-twr",
            base_url=performance_base_url,
            path="/performance/composites/twr",
            payload=twr_payload,
            correlation_id="rfc049-performance-ready-twr",
            output_dir=output_dir,
        ),
        _probe(
            name="performance-inspection",
            base_url=performance_base_url,
            path="/performance/composites/inspect",
            payload=inspection_payload,
            correlation_id="rfc049-performance-inspection",
            output_dir=output_dir,
        ),
        _probe(
            name="performance-degraded-twr",
            base_url=performance_base_url,
            path="/performance/composites/twr",
            payload=degraded_payload,
            correlation_id="rfc049-performance-degraded-twr",
            output_dir=output_dir,
        ),
        _probe(
            name="performance-no-facts-error",
            base_url=performance_base_url,
            path="/performance/composites/twr",
            payload=no_facts_payload,
            correlation_id="rfc049-performance-no-facts-error",
            output_dir=output_dir,
        ),
        _probe(
            name="gateway-ready-twr",
            base_url=gateway_base_url,
            path="/api/v1/performance/composites/twr",
            payload=twr_payload,
            correlation_id="rfc049-gateway-ready-twr",
            output_dir=output_dir,
        ),
        _probe(
            name="gateway-inspection",
            base_url=gateway_base_url,
            path="/api/v1/performance/composites/inspect",
            payload=inspection_payload,
            correlation_id="rfc049-gateway-inspection",
            output_dir=output_dir,
        ),
        _probe(
            name="workbench-bff-ready-twr",
            base_url=workbench_base_url,
            path="/api/bff/api/v1/performance/composites/twr",
            payload=twr_payload,
            correlation_id="rfc049-workbench-bff-ready-twr",
            output_dir=output_dir,
        ),
        _probe(
            name="workbench-bff-inspection",
            base_url=workbench_base_url,
            path="/api/bff/api/v1/performance/composites/inspect",
            payload=inspection_payload,
            correlation_id="rfc049-workbench-bff-inspection",
            output_dir=output_dir,
        ),
    ]

    checks: list[str] = []
    for result in probes:
        if result.name.endswith("ready-twr"):
            checks.extend(_validate_ready_twr(result))
        elif result.name.endswith("inspection"):
            checks.extend(_validate_inspection(result))
        elif result.name.endswith("degraded-twr"):
            checks.extend(_validate_degraded_twr(result))
        elif result.name.endswith("no-facts-error"):
            checks.extend(_validate_no_facts(result))
        if result.name.startswith("gateway") or result.name.startswith("workbench-bff"):
            if result.payload.get("source_service") != "lotus-performance":
                raise AssertionError(f"{result.name} did not preserve lotus-performance source_service")
            if not result.payload.get("correlation_id"):
                raise AssertionError(f"{result.name} did not return a correlation_id")

    manifest = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "proof_scope": "RFC 049 Slice 12 live composite performance proof",
        "performance_base_url": performance_base_url,
        "gateway_base_url": gateway_base_url,
        "workbench_base_url": workbench_base_url,
        "fixture_composites": ["PB_GLOBAL_BALANCED_USD", "PB_GLOBAL_BALANCED_USD_DEGRADED"],
        "checks": checks,
        "artifacts": [str(output_dir / f"{result.name}.json") for result in probes],
    }
    _write_json(output_dir / "rfc-049-slice12-live-proof-manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture and verify RFC 049 live composite performance proof.")
    parser.add_argument("--output-dir", default="output/rfc-049-slice12-live-proof")
    parser.add_argument("--performance-base-url", default="http://performance.dev.lotus")
    parser.add_argument("--gateway-base-url", default="http://gateway.dev.lotus")
    parser.add_argument("--workbench-base-url", default="http://workbench.dev.lotus")
    args = parser.parse_args()

    manifest = capture_live_proof(
        output_dir=Path(args.output_dir),
        performance_base_url=args.performance_base_url,
        gateway_base_url=args.gateway_base_url,
        workbench_base_url=args.workbench_base_url,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
