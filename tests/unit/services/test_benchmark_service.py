from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pandas as pd
import pytest

from app.models.benchmark_analytics_requests import BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.services import benchmark_service
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_BENCHMARK
from app.services.benchmark_calculation_service import BenchmarkCalculationArtifacts


@dataclass
class _BenchmarkArtifactsStub:
    results_by_period: dict
    effective_period_start: date
    notes: list[str]
    daily_returns_df: pd.DataFrame
    component_contributions_df: pd.DataFrame
    max_weight_sum_deviation: float


def _benchmark_request() -> BenchmarkPerformanceRequest:
    return BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "SI", "frequencies": ["daily"]}],
            "return_source": "calculated",
            "benchmark_currency": "USD",
            "component_observations": [
                {
                    "component_id": "IDX_1",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_return": 0.01,
                }
            ],
        }
    )


def _results_by_period() -> dict[str, object]:
    return {
        "SI": {
            "benchmark": {
                "summary": {
                    "period_return": {"base": 1.0, "local": None, "fx": None},
                    "cumulative_return": {"base": 1.0, "local": None, "fx": None},
                },
                "breakdowns": {
                    "daily": [
                        {
                            "period": "2025-01-01",
                            "period_start": "2025-01-01",
                            "period_end": "2025-01-01",
                            "period_return": {"base": 1.0, "local": None, "fx": None},
                            "cumulative_return": {"base": 1.0, "local": None, "fx": None},
                            "annualized_return": None,
                            "daily_data": None,
                        }
                    ]
                },
                "benchmark_id": "BMK_1",
                "benchmark_currency": "USD",
                "input_mode": "stateless",
                "return_source": "calculated",
            },
            "daily_returns": [
                {
                    "date": "2025-01-01",
                    "benchmark_return": 1.0,
                    "cumulative_return": 1.0,
                    "benchmark_return_local": None,
                    "benchmark_return_fx": None,
                }
            ],
            "component_contributions": [
                {
                    "date": "2025-01-01",
                    "component_id": "IDX_1",
                    "component_currency": "USD",
                    "weight_bop": 1.0,
                    "component_return": 1.0,
                    "component_return_local": None,
                    "component_return_fx": None,
                    "contribution": 1.0,
                    "local_contribution": None,
                    "fx_contribution": None,
                }
            ],
        }
    }


def test_build_completed_benchmark_response_preserves_metadata_diagnostics_and_audit():
    request = _benchmark_request()
    artifacts = BenchmarkCalculationArtifacts(
        results_by_period=_results_by_period(),
        effective_period_start=date(2025, 1, 1),
        notes=["all good"],
        daily_returns_df=pd.DataFrame([{"date": "2025-01-01"}, {"date": "2025-01-02"}]),
        component_contributions_df=pd.DataFrame([{"component_id": "IDX_1"}]),
        max_weight_sum_deviation=0.0025,
    )

    response = benchmark_service._build_completed_benchmark_response(
        benchmark_request=request,
        benchmark_artifacts=artifacts,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
        input_mode=BenchmarkInputMode.STATELESS,
        engine_version="runtime-version",
    )

    assert response.calculation_id == request.calculation_id
    assert response.return_source == request.return_source
    assert response.results_by_period["SI"].benchmark.benchmark_id == "BMK_1"
    assert response.results_by_period["SI"].benchmark.benchmark_currency == "USD"
    assert response.meta.periods == {
        "requested": ["SI"],
        "master_start": "2025-01-01",
        "master_end": "2025-01-02",
    }
    assert response.meta.input_fingerprint == "fingerprint"
    assert response.meta.calculation_hash == "hash"
    assert response.diagnostics.effective_period_start == date(2025, 1, 1)
    assert response.diagnostics.notes == ["all good"]
    assert response.audit.counts == {
        "component_observations": 1,
        "benchmark_return_points": 0,
        "daily_returns": 2,
    }
    assert response.audit.residual_applied_bp == pytest.approx(25.0)


def test_calculate_benchmark_response_builds_response_and_records_lineage(mocker):
    request = _benchmark_request()
    lineage_capture: dict[str, object] = {}
    mocker.patch.object(
        benchmark_service.execution_registry,
        "start_stage",
        lambda calculation_id, stage_name: None,
    )
    mocker.patch(
        "app.services.benchmark_service.calculate_benchmark_artifacts",
        return_value=_BenchmarkArtifactsStub(
            results_by_period=_results_by_period(),
            effective_period_start=date(2025, 1, 1),
            notes=["all good"],
            daily_returns_df=pd.DataFrame([{"date": "2025-01-01"}]),
            component_contributions_df=pd.DataFrame([{"component_id": "IDX_1"}]),
            max_weight_sum_deviation=0.001,
        ),
    )
    mocker.patch(
        "app.services.benchmark_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: lineage_capture.update(kwargs),
    )

    response = benchmark_service.calculate_benchmark_response(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
        input_mode=BenchmarkInputMode.STATELESS,
        engine_version="runtime-version",
        request_artifact_model=request,
    )

    assert response.benchmark_id == "BMK_1"
    assert response.input_mode == BenchmarkInputMode.STATELESS
    assert response.audit.counts["component_observations"] == 1
    assert response.audit.counts["daily_returns"] == 1
    assert response.audit.residual_applied_bp == pytest.approx(10.0)
    assert response.diagnostics.notes == ["all good"]
    assert response.meta.engine_version == "runtime-version"
    assert lineage_capture["calculation_type"] == ANALYTICS_WORKFLOW_BENCHMARK
    assert lineage_capture["request_model"] == request
    assert lineage_capture["response_model"] == response


def test_calculate_benchmark_response_fails_execution_stage_when_artifact_building_raises(mocker):
    request = _benchmark_request()
    failure_capture: dict[str, object] = {}
    mocker.patch.object(
        benchmark_service.execution_registry,
        "start_stage",
        lambda calculation_id, stage_name: None,
    )
    mocker.patch(
        "app.services.benchmark_service.calculate_benchmark_artifacts",
        side_effect=RuntimeError("artifact failure"),
    )
    mocker.patch.object(
        benchmark_service.execution_registry,
        "fail_stage",
        side_effect=lambda calculation_id, stage_name, message: failure_capture.update(
            {"calculation_id": calculation_id, "stage_name": stage_name, "message": message}
        ),
    )

    with pytest.raises(RuntimeError, match="artifact failure"):
        benchmark_service.calculate_benchmark_response(
            request,
            input_fingerprint="fingerprint",
            calculation_hash="hash",
            input_mode=BenchmarkInputMode.STATELESS,
            engine_version="runtime-version",
            request_artifact_model=request,
        )

    assert failure_capture["calculation_id"] == request.calculation_id
    assert failure_capture["stage_name"] == "execution"
    assert failure_capture["message"] == "artifact failure"
