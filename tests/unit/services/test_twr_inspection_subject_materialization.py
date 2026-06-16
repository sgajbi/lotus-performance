import json
from types import SimpleNamespace
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


def test_existing_artifacts_from_lineage_payload_materializes_response_and_request(monkeypatch):
    calculation_id = uuid4()
    response_payload = _performance_response_payload(calculation_id=str(calculation_id))
    request_payload = {"resolved_request": _resolved_request_payload()}

    monkeypatch.setattr(materialization, "_load_request_payload", lambda _calculation_id: request_payload)

    artifacts = materialization._existing_artifacts_from_lineage_payload(
        calculation_id=calculation_id,
        payload=SimpleNamespace(
            response_json=json.dumps(response_payload),
            request_json=json.dumps(request_payload),
        ),
    )

    assert artifacts is not None
    assert artifacts.response_model.calculation_id == calculation_id
    assert artifacts.request_payload == request_payload


def test_existing_artifacts_from_lineage_payload_skips_invalid_response(caplog):
    calculation_id = uuid4()

    with caplog.at_level("WARNING", logger="app.services.inspection.subject_materialization"):
        artifacts = materialization._existing_artifacts_from_lineage_payload(
            calculation_id=calculation_id,
            payload=SimpleNamespace(response_json="{not-json"),
        )

    assert artifacts is None
    assert f"calculation_id={calculation_id}" in caplog.text


def test_request_payload_from_lineage_payload_reads_request_json():
    calculation_id = uuid4()
    request_payload = {"resolved_request": _resolved_request_payload()}

    assert (
        materialization._request_payload_from_lineage_payload(
            calculation_id=calculation_id,
            payload=SimpleNamespace(request_json=json.dumps(request_payload)),
        )
        == request_payload
    )


def test_request_payload_from_lineage_payload_skips_absent_or_invalid_request(caplog):
    calculation_id = uuid4()

    assert materialization._request_payload_from_lineage_payload(calculation_id=calculation_id, payload=None) is None
    with caplog.at_level("WARNING", logger="app.services.inspection.subject_materialization"):
        request_payload = materialization._request_payload_from_lineage_payload(
            calculation_id=calculation_id,
            payload=SimpleNamespace(request_json="{not-json"),
        )

    assert request_payload is None
    assert f"calculation_id={calculation_id}" in caplog.text


def test_load_existing_twr_calculation_artifacts_waits_for_lineage_request_payload(monkeypatch, tmp_path):
    calculation_id = uuid4()
    response_payload = _performance_response_payload(calculation_id=str(calculation_id))
    request_payload = {"resolved_request": _resolved_request_payload()}
    lineage_calls = {"count": 0}

    def _get_payload(_calculation_id):
        lineage_calls["count"] += 1
        if lineage_calls["count"] == 1:
            return None
        return SimpleNamespace(
            request_json=json.dumps(request_payload),
            response_json=json.dumps(response_payload),
        )

    monkeypatch.setattr(
        materialization, "get_settings", lambda: type("Settings", (), {"LINEAGE_STORAGE_PATH": str(tmp_path)})()
    )
    monkeypatch.setattr(
        materialization.async_result_store,
        "get_result",
        lambda _calculation_id: SimpleNamespace(response_payload=response_payload),
    )
    monkeypatch.setattr(materialization.lineage_metadata_store, "get_payload", _get_payload)
    monkeypatch.setattr(materialization.compute_job_store, "get_job", lambda _calculation_id: None)

    artifacts = load_existing_twr_calculation_artifacts(calculation_id)

    assert artifacts.response_model.calculation_id == calculation_id
    assert artifacts.request_payload == request_payload
    assert lineage_calls["count"] == 2


def test_load_existing_twr_calculation_artifacts_reads_compute_job_request_payload(monkeypatch, tmp_path):
    calculation_id = uuid4()
    response_payload = _performance_response_payload(calculation_id=str(calculation_id))
    request_payload = {"resolved_request": _resolved_request_payload()}

    monkeypatch.setattr(
        materialization, "get_settings", lambda: type("Settings", (), {"LINEAGE_STORAGE_PATH": str(tmp_path)})()
    )
    monkeypatch.setattr(
        materialization.async_result_store,
        "get_result",
        lambda _calculation_id: SimpleNamespace(response_payload=response_payload),
    )
    monkeypatch.setattr(materialization.lineage_metadata_store, "get_payload", lambda _calculation_id: None)
    monkeypatch.setattr(
        materialization.compute_job_store,
        "get_job",
        lambda _calculation_id: SimpleNamespace(request_payload=request_payload),
    )

    artifacts = load_existing_twr_calculation_artifacts(calculation_id)

    assert artifacts.response_model.calculation_id == calculation_id
    assert artifacts.request_payload == request_payload


def test_load_existing_twr_calculation_artifacts_skips_invalid_lineage_response_json(monkeypatch, tmp_path, caplog):
    calculation_id = uuid4()
    response_payload = _performance_response_payload(calculation_id=str(calculation_id))
    request_payload = {"resolved_request": _resolved_request_payload()}

    monkeypatch.setattr(
        materialization, "get_settings", lambda: type("Settings", (), {"LINEAGE_STORAGE_PATH": str(tmp_path)})()
    )
    monkeypatch.setattr(
        materialization.lineage_metadata_store,
        "get_payload",
        lambda _calculation_id: SimpleNamespace(request_json=json.dumps(request_payload), response_json="{not-json"),
    )
    monkeypatch.setattr(
        materialization.async_result_store,
        "get_result",
        lambda _calculation_id: SimpleNamespace(response_payload=response_payload),
    )
    monkeypatch.setattr(
        materialization.compute_job_store,
        "get_job",
        lambda _calculation_id: SimpleNamespace(request_payload=request_payload),
    )

    with caplog.at_level("WARNING", logger="app.services.inspection.subject_materialization"):
        artifacts = load_existing_twr_calculation_artifacts(calculation_id)

    assert artifacts.response_model.calculation_id == calculation_id
    assert artifacts.request_payload == request_payload
    assert f"calculation_id={calculation_id}" in caplog.text


def test_load_existing_twr_calculation_artifacts_skips_invalid_lineage_request_json(monkeypatch, tmp_path, caplog):
    calculation_id = uuid4()
    response_payload = _performance_response_payload(calculation_id=str(calculation_id))
    request_payload = {"resolved_request": _resolved_request_payload()}

    monkeypatch.setattr(
        materialization, "get_settings", lambda: type("Settings", (), {"LINEAGE_STORAGE_PATH": str(tmp_path)})()
    )
    monkeypatch.setattr(
        materialization.lineage_metadata_store,
        "get_payload",
        lambda _calculation_id: SimpleNamespace(request_json="{not-json", response_json=json.dumps(response_payload)),
    )
    monkeypatch.setattr(materialization.async_result_store, "get_result", lambda _calculation_id: None)
    monkeypatch.setattr(
        materialization.compute_job_store,
        "get_job",
        lambda _calculation_id: SimpleNamespace(request_payload=request_payload),
    )

    with caplog.at_level("WARNING", logger="app.services.inspection.subject_materialization"):
        artifacts = load_existing_twr_calculation_artifacts(calculation_id)

    assert artifacts.response_model.calculation_id == calculation_id
    assert artifacts.request_payload == request_payload
    assert f"calculation_id={calculation_id}" in caplog.text


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


def test_extract_performance_request_propagates_unexpected_resolved_parser_errors(monkeypatch):
    def _raise_runtime_error(_payload):
        raise RuntimeError("parser dependency failed")

    monkeypatch.setattr(materialization.TWRResolvedExecutionRequest, "model_validate", _raise_runtime_error)

    with pytest.raises(RuntimeError, match="parser dependency failed"):
        extract_performance_request_from_payload({"resolved_request": _resolved_request_payload()})


def test_extract_resolved_execution_request_propagates_unexpected_parser_errors(monkeypatch):
    def _raise_runtime_error(_payload):
        raise RuntimeError("parser dependency failed")

    monkeypatch.setattr(materialization.TWRResolvedExecutionRequest, "model_validate", _raise_runtime_error)

    with pytest.raises(RuntimeError, match="parser dependency failed"):
        extract_resolved_execution_request_from_payload({"resolved_request": _resolved_request_payload()})


def test_extract_performance_request_propagates_unexpected_analytics_parser_errors(monkeypatch):
    original_resolved_model_validate = materialization.TWRResolvedExecutionRequest.model_validate

    def _raise_validation_error(_payload):
        return original_resolved_model_validate({"portfolio": {"portfolio_id": object()}})

    def _raise_runtime_error(_payload):
        raise RuntimeError("analytics parser dependency failed")

    monkeypatch.setattr(materialization.TWRResolvedExecutionRequest, "model_validate", _raise_validation_error)
    monkeypatch.setattr(materialization.TWRAnalyticsRequest, "model_validate", _raise_runtime_error)

    with pytest.raises(RuntimeError, match="analytics parser dependency failed"):
        extract_performance_request_from_payload(_analytics_request_payload())


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
