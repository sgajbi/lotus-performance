import json
from uuid import uuid4

import pytest

import app.services.inspection.subject_materialization as materialization
from app.services.inspection.subject_materialization import (
    extract_performance_request_from_payload,
    extract_resolved_execution_request_from_payload,
    load_existing_twr_calculation_artifacts,
)


def test_extract_resolved_execution_request_accepts_wrapped_stateful_lineage_payload():
    payload = {
        "resolved_request": {
            "portfolio": {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "performance_start_date": "2026-01-01",
                "metric_basis": "NET",
                "report_end_date": "2026-04-10",
                "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                "valuation_points": [
                    {
                        "perf_date": "2026-01-01",
                        "begin_mv": 1000.0,
                        "end_mv": 1001.0,
                        "bod_cf": 0.0,
                        "eod_cf": 0.0,
                        "mgmt_fees": 0.0,
                    }
                ],
            },
            "benchmark": None,
        },
        "source_input_mode": "stateful",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
    }

    resolved_request = extract_resolved_execution_request_from_payload(payload)
    performance_request = extract_performance_request_from_payload(payload)

    assert resolved_request is not None
    assert resolved_request.portfolio.portfolio_id == "PB_SG_GLOBAL_BAL_001"
    assert performance_request is not None
    assert performance_request.valuation_points[0].perf_date.isoformat() == "2026-01-01"


def test_load_existing_twr_calculation_artifacts_reads_materialized_lineage_files(monkeypatch, tmp_path):
    calculation_id = uuid4()
    artifact_dir = tmp_path / str(calculation_id)
    artifact_dir.mkdir()
    response_payload = _performance_response_payload(calculation_id=str(calculation_id))
    request_payload = {"resolved_request": _resolved_request_payload()}
    (artifact_dir / "response.json").write_text(json.dumps(response_payload), encoding="utf-8")
    (artifact_dir / "request.json").write_text(json.dumps(request_payload), encoding="utf-8")

    monkeypatch.setattr(
        materialization, "get_settings", lambda: type("Settings", (), {"LINEAGE_STORAGE_PATH": str(tmp_path)})()
    )
    monkeypatch.setattr(materialization.async_result_store, "get_result", lambda _calculation_id: None)
    monkeypatch.setattr(materialization.lineage_metadata_store, "get_payload", lambda _calculation_id: None)

    artifacts = load_existing_twr_calculation_artifacts(calculation_id)

    assert artifacts.response_model.calculation_id == calculation_id
    assert artifacts.request_payload == request_payload


def test_load_existing_twr_calculation_artifacts_raises_when_no_response_source(monkeypatch, tmp_path):
    calculation_id = uuid4()
    monkeypatch.setattr(
        materialization, "get_settings", lambda: type("Settings", (), {"LINEAGE_STORAGE_PATH": str(tmp_path)})()
    )
    monkeypatch.setattr(materialization.async_result_store, "get_result", lambda _calculation_id: None)
    monkeypatch.setattr(materialization.lineage_metadata_store, "get_payload", lambda _calculation_id: None)

    with pytest.raises(KeyError, match="TWR response artifacts not found"):
        load_existing_twr_calculation_artifacts(calculation_id)


def test_extract_performance_request_rejects_non_stateless_and_invalid_payloads():
    stateful_payload = _analytics_request_payload()
    stateful_payload["input_mode"] = "stateful"
    stateful_payload.pop("valuation_points")
    stateful_payload["stateful_input"] = {"consumer_system": "lotus-performance"}

    assert extract_performance_request_from_payload(stateful_payload) is None
    assert extract_performance_request_from_payload({"portfolio_id": object()}) is None
    assert extract_resolved_execution_request_from_payload({"portfolio": {"portfolio_id": object()}}) is None


def _analytics_request_payload() -> dict:
    return {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "performance_start_date": "2026-01-01",
        "metric_basis": "NET",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2026-01-02", "begin_mv": 1000.0, "end_mv": 1001.0}],
    }


def _resolved_request_payload() -> dict:
    return {
        "portfolio": _analytics_request_payload(),
        "benchmark": None,
    }


def _performance_response_payload(*, calculation_id: str) -> dict:
    return {
        "calculation_id": calculation_id,
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "input_mode": "stateless",
        "results_by_period": {
            "YTD": {
                "portfolio": {
                    "summary": {
                        "period_return": {"base": 0.1, "local": None, "fx": None},
                        "cumulative_return": {"base": 0.1, "local": None, "fx": None},
                    },
                    "breakdowns": {"daily": []},
                    "benchmark_id": None,
                },
                "benchmark": None,
                "relative_performance": None,
                "reset_events": [],
            }
        },
        "calculation_supportability": {
            "state": "ready",
            "reason": "calculation_complete",
            "freshness_bucket": "current",
            "input_row_count": 1,
            "resolved_period_count": 1,
            "benchmark_row_count": 0,
        },
        "meta": {
            "calculation_id": calculation_id,
            "engine_version": "test",
            "precision_mode": "FLOAT64",
            "annualization": {"enabled": False, "basis": "BUS/252", "periods_per_year": None},
            "calendar": {"type": "BUSINESS", "trading_calendar": "NYSE"},
            "periods": {"master_start": "2026-01-02", "master_end": "2026-01-02"},
        },
        "diagnostics": {"nip_days": 0, "reset_days": 0, "effective_period_start": "2026-01-02", "notes": []},
        "audit": {"counts": {}},
    }
