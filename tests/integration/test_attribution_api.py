import asyncio
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest
from app.models.benchmark_requests import BenchmarkComponentObservation
from app.observability_contracts import PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS
from app.services.async_result_store import async_result_store
from app.services.attribution_mode_service import resolve_attribution_request
from app.services.calculation_engine_version import calculation_engine_version
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import ExecutionStageStatus, ExecutionStatus, execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_SUBMISSION
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.stateful_benchmark_input_service import StatefulBenchmarkNormalizedInput
from core.periods import ResolvedPeriod
from core.repro import generate_canonical_hash
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from main import app
from tests.conftest import drain_compute_queue, drain_lineage_queue

settings = get_settings()


@pytest.mark.parametrize("shape", ["legacy", "nested", "stateful"])
@pytest.mark.parametrize("async_requested", [False, True])
def test_attribution_strict_precision_refused_before_source_or_job_admission(
    client, monkeypatch, shape, async_requested
):
    payload = _single_period_sector_attribution_payload(model="BF", portfolio_weights=(0.6, 0.4))
    calculation_id = uuid4()
    payload.update(calculation_id=str(calculation_id), precision_mode="DECIMAL_STRICT")
    if shape == "nested":
        payload["stateless_input"] = {
            key: payload.pop(key) for key in ("portfolio_groups_data", "benchmark_groups_data")
        }
    elif shape == "stateful":
        payload.pop("portfolio_groups_data")
        payload.pop("benchmark_groups_data")
        payload.update(mode="by_instrument", input_mode="stateful", stateful_input={"metric_basis": "NET"})

    async def unexpected_source_read(*args, **kwargs):
        raise AssertionError("Unsupported precision must be refused before source resolution")

    monkeypatch.setattr(
        "app.services.attribution_calculation_workflow_service.resolve_attribution_request", unexpected_source_read
    )
    headers = {"Idempotency-Key": "precision-refusal"} if async_requested else {}
    response = client.post("/performance/attribution", json=payload, headers=headers)
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["retryable"] is False
    assert any(
        error["type"] == "ATTRIBUTION_PRECISION_UNSUPPORTED" and error["loc"] == ["body", "precision_mode"]
        for error in body["validation_errors"]
    )
    assert execution_registry.get_execution(calculation_id) is None
    assert compute_job_store.get_job(calculation_id) is None


def test_instrument_attribution_preserves_independent_cent_profit_beside_large_deposit(client, monkeypatch):
    import engine.attribution as attribution_engine

    actual_engine = attribution_engine.run_engine_for_valuation_points
    executed_modes = []

    def capture_actual_engine(points, config, **kwargs):
        executed_modes.append(config.precision_mode.value)
        return actual_engine(points, config, **kwargs)

    monkeypatch.setattr(attribution_engine, "run_engine_for_valuation_points", capture_actual_engine)
    points = [
        {"perf_date": "2025-01-01", "begin_mv": "100", "end_mv": "9007199254741093.02", "eod_cf": "9007199254740993.01"}
    ]
    payload = {
        "portfolio_id": "EXACT_ATTRIBUTION_DEPOSIT",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "model": "BF",
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {"metric_basis": "GROSS", "valuation_points": points},
        "instruments_data": [
            {"instrument_id": "FUNDED_ASSET", "meta": {"sector": "Control"}, "valuation_points": points}
        ],
        "benchmark_groups_data": [
            {"key": {"sector": "Control"}, "observations": [{"date": "2025-01-01", "return_base": 0, "weight_bop": 1}]}
        ],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200, response.text
    assert executed_modes == ["FLOAT64"]
    assert response.json()["meta"]["precision_mode"] == "FLOAT64"
    period = response.json()["results_by_period"]["SI"]
    assert period["reconciliation"]["total_active_return"] == pytest.approx(0.01, abs=1e-12)
    assert period["reconciliation"]["sum_of_effects"] == pytest.approx(0.01, abs=1e-12)
    group = period["levels"][0]["groups"][0]
    assert group["portfolio_return"] == pytest.approx(0.01, abs=1e-12)
    assert group["selection"] == pytest.approx(0.01, abs=1e-12)


@pytest.mark.parametrize("weights", [("0.6", "0.4"), ("1.2", "-0.2"), ("0", "1")])
def test_attribution_float64_signed_zero_weight_independent_effects(client, weights):
    payload = _single_period_sector_attribution_payload(model="BF", portfolio_weights=tuple(map(float, weights)))
    payload["precision_mode"] = "FLOAT64"
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["precision_mode"] == "FLOAT64"
    period = response.json()["results_by_period"]["SI"]
    # Independent one-day BF equations. Linking NONE reports the arithmetic difference,
    # not the relative wealth ratio (1 + Rp) / (1 + Rb) - 1.
    wp = list(map(Decimal, weights))
    wb = [Decimal("0.5"), Decimal("0.5")]
    rp = [Decimal("0.10"), Decimal("0")]
    rb = [Decimal("0.04"), Decimal("0.02")]
    portfolio_return = sum(w * r for w, r in zip(wp, rp))
    benchmark_return = Decimal("0.03")
    active = portfolio_return - benchmark_return
    groups = {group["key"]["sector"]: group for group in period["levels"][0]["groups"]}
    for index, name in enumerate(("Tech", "Health")):
        expected = {
            "allocation": (wp[index] - wb[index]) * (rb[index] - benchmark_return),
            "selection": wb[index] * (rp[index] - rb[index]),
            "interaction": (wp[index] - wb[index]) * (rp[index] - rb[index]),
        }
        for effect, value in expected.items():
            assert groups[name][effect] == pytest.approx(float(value * 100), abs=1e-12)
    assert period["reconciliation"]["total_active_return"] == pytest.approx(float(active * 100), abs=1e-12)


_EXPECTED_SUPPORTABILITY_METRIC_LABELS = list(PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS)


def _stateful_benchmark_input(*observations: BenchmarkComponentObservation) -> StatefulBenchmarkNormalizedInput:
    component_ids = {observation.component_id for observation in observations}
    return StatefulBenchmarkNormalizedInput(
        benchmark_currency="USD",
        component_observations=list(observations),
        benchmark_return_points=[],
        source_details={
            "benchmark_components": len(component_ids),
            "component_observations": len(observations),
            "benchmark_chunk_count": 1,
            "benchmark_page_count": 1,
            "fx_pair_count": 0,
            "fx_chunk_count": 0,
            "fx_page_count": 0,
        },
    )


def _patch_stateful_attribution_benchmark_input(monkeypatch, *observations: BenchmarkComponentObservation) -> None:
    async def _mock_build_stateful_benchmark_input(**kwargs):  # noqa: ARG001
        return _stateful_benchmark_input(*observations)

    monkeypatch.setattr(
        "app.services.stateful_attribution_input_service.build_stateful_benchmark_input",
        _mock_build_stateful_benchmark_input,
    )


def _assert_authoritative_level_totals(level: dict) -> None:
    totals = level["totals"]
    assert level["allocation_total_pct"] == pytest.approx(totals["allocation"])
    assert level["selection_total_pct"] == pytest.approx(totals["selection"])
    assert level["interaction_total_pct"] == pytest.approx(totals["interaction"])
    assert level["total_effect_pct"] == pytest.approx(totals["total_effect"])
    assert level["allocation_total_pct"] == pytest.approx(sum(group["allocation"] for group in level["groups"]))
    assert level["selection_total_pct"] == pytest.approx(sum(group["selection"] for group in level["groups"]))
    assert level["interaction_total_pct"] == pytest.approx(sum(group["interaction"] for group in level["groups"]))
    assert level["total_effect_pct"] == pytest.approx(sum(group["total_effect"] for group in level["groups"]))
    assert level["total_effect_pct"] == pytest.approx(
        level["allocation_total_pct"] + level["selection_total_pct"] + level["interaction_total_pct"]
    )


def _single_period_sector_attribution_payload(
    *,
    model: str,
    portfolio_weights: tuple[float, float],
) -> dict:
    return {
        "portfolio_id": f"ATTRIB_{model}_INTERACTION",
        "mode": "by_group",
        "group_by": ["sector"],
        "model": model,
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.10, "weight_bop": portfolio_weights[0]}],
            },
            {
                "key": {"sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.00, "weight_bop": portfolio_weights[1]}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.04, "weight_bop": 0.50}],
            },
            {
                "key": {"sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.50}],
            },
        ],
    }


@pytest.fixture()
def client():
    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    os.makedirs(settings.LINEAGE_STORAGE_PATH, exist_ok=True)
    execution_registry.create_schema()
    execution_registry.clear_all_records()
    compute_job_store.create_schema()
    compute_job_store.clear_all_records()
    async_result_store.create_schema()
    async_result_store.clear_all_records()
    lineage_metadata_store.create_schema()
    lineage_metadata_store.clear_all_records()

    with TestClient(app, headers={"X-Tenant-Id": "tenant-a"}) as c:
        yield c

    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    compute_job_store.clear_all_records()
    async_result_store.clear_all_records()
    execution_registry.clear_all_records()
    lineage_metadata_store.clear_all_records()


def test_attribution_endpoint_by_instrument_happy_path(client):
    """Tests the /performance/attribution endpoint end-to-end with a valid 'by_instrument' payload."""
    payload = {
        "portfolio_id": "ATTRIB_BY_INST_01",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1018.5}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"sector": "Tech"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612}],
            },
            {
                "instrument_id": "JNJ",
                "meta": {"sector": "Health"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 406.5}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 0.5}],
            },
            {
                "key": {"sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.5}],
            },
        ],
    }

    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["diagnostics"]["nip_days"] == 0
    assert body["diagnostics"]["reset_days"] == 0
    assert body["diagnostics"]["effective_period_start"] == "2025-01-01"
    assert body["diagnostics"]["samples"]["period_status_counts"] == [{"valid": 1}]
    assert body["diagnostics"]["samples"]["residual_materiality_counts"] == [{"immaterial": 1}]
    assert body["audit"]["counts"] == {
        "input_row_count": 5,
        "portfolio_row_count": 3,
        "benchmark_row_count": 2,
        "resolved_period_count": 1,
        "level_count": 1,
        "group_count": 2,
        "reason_count": 0,
        "supportability_issue_count": 0,
        "periods_with_material_residual": 0,
        "periods_with_watch_residual": 0,
        "benchmark_context_count": 0,
    }
    assert body["calculation_supportability"] == {
        "state": "ready",
        "reason": "calculation_complete",
        "freshness_bucket": "current",
        "input_row_count": 5,
        "resolved_period_count": 1,
        "benchmark_row_count": 2,
        "source_quality_evidence": None,
        "history_coverage": None,
        "metric_labels": _EXPECTED_SUPPORTABILITY_METRIC_LABELS,
    }
    response_data = body["results_by_period"]["SI"]
    assert response_data["status"] == "valid"
    assert response_data["reason_codes"] == []
    assert response_data["supportability_evidence"]["portfolio_only_group_count"] == 0
    assert response_data["supportability_evidence"]["benchmark_only_group_count"] == 0
    assert response_data["supportability_evidence"]["currency_attribution_status"] == "not_requested"
    assert response_data["supportability_evidence"]["linking_status"] == "not_requested"
    assert response_data["reconciliation"]["residual_materiality"]["classification"] == "immaterial"
    assert response_data["reconciliation"]["total_active_return"] == pytest.approx(0.1)
    level = response_data["levels"][0]
    _assert_authoritative_level_totals(level)
    assert response_data["reconciliation"]["sum_of_effects"] == pytest.approx(level["total_effect_pct"])
    tech_group = next(g for g in level["groups"] if g["key"]["sector"] == "Tech")
    assert tech_group["portfolio_weight_avg"] == pytest.approx(60.0)
    assert tech_group["benchmark_weight_avg"] == pytest.approx(50.0)
    assert tech_group["portfolio_return"] == pytest.approx(2.0)
    assert tech_group["benchmark_return"] == pytest.approx(1.5)
    assert tech_group["selection"] == pytest.approx(0.25)
    assert tech_group["total_effect"] == pytest.approx(
        tech_group["allocation"] + tech_group["selection"] + tech_group["interaction"]
    )


def test_attribution_endpoint_qualifies_near_zero_linking_denominator(client):
    payload = {
        "portfolio_id": "ATTRIB_NEAR_ZERO_LINKING",
        "mode": "by_group",
        "group_by": ["sector"],
        "model": "BF",
        "linking": "carino",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "One"},
                "observations": [
                    {"date": "2025-01-01", "return_base": 0.1, "weight_bop": 1.0},
                    {"date": "2025-01-02", "return_base": -0.1, "weight_bop": 1.0},
                ],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "One"},
                "observations": [
                    {"date": "2025-01-01", "return_base": 0.0, "weight_bop": 1.0},
                    {"date": "2025-01-02", "return_base": 0.0, "weight_bop": 1.0},
                ],
            }
        ],
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    assert period["status"] == "warning"
    assert "linking_scaling_skipped" in period["reason_codes"]
    assert "material_residual" in period["reason_codes"]
    assert period["supportability_evidence"]["linking_status"] == "scaling_skipped"
    assert period["reconciliation"]["total_active_return"] == pytest.approx(-1.0, abs=1e-12)
    assert abs(period["reconciliation"]["sum_of_effects"]) < 1e-10
    assert period["reconciliation"]["residual"] == pytest.approx(-1.0, abs=1e-10)


@pytest.mark.parametrize(
    (
        "model",
        "portfolio_weights",
        "expected_active_return_pct",
        "expected_conventional_interaction_pct",
        "expected_reported_interaction_pct",
    ),
    [
        pytest.param("BHB", (0.60, 0.40), 3.0, 0.8, 0.0, id="bhb-positive-interaction"),
        pytest.param("BHB", (0.40, 0.60), 1.0, -0.8, 0.0, id="bhb-negative-interaction"),
        pytest.param("BHB", (0.50, 0.50), 2.0, 0.0, 0.0, id="bhb-zero-interaction"),
        pytest.param("BF", (0.60, 0.40), 3.0, 0.8, 0.8, id="bf-positive-interaction-control"),
    ],
)
def test_attribution_endpoint_reconciles_bhb_without_double_counting_interaction(
    client,
    model,
    portfolio_weights,
    expected_active_return_pct,
    expected_conventional_interaction_pct,
    expected_reported_interaction_pct,
):
    payload = _single_period_sector_attribution_payload(
        model=model,
        portfolio_weights=portfolio_weights,
    )

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    level = period["levels"][0]
    _assert_authoritative_level_totals(level)
    independently_calculated_portfolio_return_pct = (portfolio_weights[0] * 0.10 + portfolio_weights[1] * 0.00) * 100
    independently_calculated_benchmark_return_pct = (0.50 * 0.04 + 0.50 * 0.02) * 100
    independently_calculated_active_return_pct = (
        independently_calculated_portfolio_return_pct - independently_calculated_benchmark_return_pct
    )
    conventional_interaction_pct = (
        (portfolio_weights[0] - 0.50) * (0.10 - 0.04) + (portfolio_weights[1] - 0.50) * (0.00 - 0.02)
    ) * 100

    assert independently_calculated_active_return_pct == pytest.approx(expected_active_return_pct, abs=1e-12)
    assert conventional_interaction_pct == pytest.approx(expected_conventional_interaction_pct, abs=1e-12)
    assert level["interaction_total_pct"] == pytest.approx(expected_reported_interaction_pct, abs=1e-12)
    assert level["total_effect_pct"] == pytest.approx(independently_calculated_active_return_pct, abs=1e-12)
    assert period["reconciliation"]["total_active_return"] == pytest.approx(
        independently_calculated_active_return_pct,
        abs=1e-12,
    )
    assert period["reconciliation"]["sum_of_effects"] == pytest.approx(
        independently_calculated_active_return_pct,
        abs=1e-12,
    )
    assert period["reconciliation"]["residual"] == pytest.approx(0.0, abs=1e-12)
    assert period["reconciliation"]["residual_materiality"]["classification"] == "immaterial"


def test_attribution_endpoint_by_instrument_applies_corrected_bhb_decomposition(client):
    payload = {
        "portfolio_id": "ATTRIB_BHB_BY_INSTRUMENT",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "model": "BHB",
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1060}],
        },
        "instruments_data": [
            {
                "instrument_id": "TECH_POSITION",
                "meta": {"sector": "Tech"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 660}],
            },
            {
                "instrument_id": "HEALTH_POSITION",
                "meta": {"sector": "Health"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 400}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.04, "weight_bop": 0.50}],
            },
            {
                "key": {"sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.50}],
            },
        ],
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    period = response.json()["results_by_period"]["SI"]
    level = period["levels"][0]
    _assert_authoritative_level_totals(level)
    groups = {group["key"]["sector"]: group for group in level["groups"]}

    assert groups["Tech"] == {
        "key": {"sector": "Tech"},
        "portfolio_weight_avg": pytest.approx(60.0),
        "benchmark_weight_avg": pytest.approx(50.0),
        "portfolio_return": pytest.approx(10.0),
        "benchmark_return": pytest.approx(4.0),
        "allocation": pytest.approx(0.4),
        "selection": pytest.approx(3.6),
        "interaction": pytest.approx(0.0),
        "total_effect": pytest.approx(4.0),
    }
    assert groups["Health"] == {
        "key": {"sector": "Health"},
        "portfolio_weight_avg": pytest.approx(40.0),
        "benchmark_weight_avg": pytest.approx(50.0),
        "portfolio_return": pytest.approx(0.0),
        "benchmark_return": pytest.approx(2.0),
        "allocation": pytest.approx(-0.2),
        "selection": pytest.approx(-0.8),
        "interaction": pytest.approx(0.0),
        "total_effect": pytest.approx(-1.0),
    }

    independently_calculated_active_return_pct = ((600 / 1000) * 0.10 + (400 / 1000) * 0.00) * 100 - (
        0.50 * 0.04 + 0.50 * 0.02
    ) * 100
    assert independently_calculated_active_return_pct == pytest.approx(3.0, abs=1e-12)
    assert level["allocation_total_pct"] == pytest.approx(0.2, abs=1e-12)
    assert level["selection_total_pct"] == pytest.approx(2.8, abs=1e-12)
    assert level["interaction_total_pct"] == pytest.approx(0.0, abs=1e-12)
    assert level["total_effect_pct"] == pytest.approx(independently_calculated_active_return_pct, abs=1e-12)
    assert period["reconciliation"]["total_active_return"] == pytest.approx(
        independently_calculated_active_return_pct,
        abs=1e-12,
    )
    assert period["reconciliation"]["sum_of_effects"] == pytest.approx(
        independently_calculated_active_return_pct,
        abs=1e-12,
    )
    assert period["reconciliation"]["residual"] == pytest.approx(0.0, abs=1e-12)
    assert period["reconciliation"]["residual_materiality"]["classification"] == "immaterial"


def test_attribution_lineage_flow(client):
    """Tests that lineage is correctly captured for an attribution request."""
    payload = {
        "portfolio_id": "ATTRIB_LINEAGE_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.02, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    attrib_response = client.post("/performance/attribution", json=payload)
    assert attrib_response.status_code == 200
    calculation_id = attrib_response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1

    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200
    lineage_data = lineage_response.json()

    assert lineage_data["calculation_type"] == "Attribution"
    assert "aligned_panel.csv" in lineage_data["artifacts"]
    assert "single_period_effects.csv" in lineage_data["artifacts"]
    assert "SI_attribution_supportability_evidence.csv" in lineage_data["artifacts"]


def test_attribution_endpoint_emits_controlled_status_reason_and_supportability_evidence(client):
    payload = {
        "portfolio_id": "ATTRIB_STATUS_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Technology"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.7}],
            },
            {
                "key": {"sector": "unknown"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.3}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Technology"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.6}],
            },
            {
                "key": {"sector": "Benchmark Only"},
                "observations": [{"date": "2025-01-01", "return_base": 0.005, "weight_bop": 0.4}],
            },
        ],
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    period = body["results_by_period"]["SI"]
    assert period["status"] == "partial"
    assert set(period["reason_codes"]) >= {
        "off_benchmark_exposure",
        "benchmark_only_exposure",
        "unclassified_segment",
    }
    assert period["supportability_evidence"]["portfolio_only_group_count"] == 1
    assert period["supportability_evidence"]["benchmark_only_group_count"] == 1
    assert period["supportability_evidence"]["unclassified_group_count"] == 1
    assert body["diagnostics"]["samples"]["period_status_counts"] == [{"partial": 1}]
    assert body["diagnostics"]["samples"]["supportability_evidence_counts"] == [
        {
            "portfolio_only_group_count": 1,
            "benchmark_only_group_count": 1,
            "unclassified_group_count": 1,
            "missing_benchmark_return_count": 0,
            "negative_weight_count": 0,
            "zero_portfolio_exposure_count": 0,
        }
    ]
    assert body["audit"]["counts"]["supportability_issue_count"] == 3
    assert body["audit"]["counts"]["reason_count"] == 3
    assert all(reason["message"] for reason in period["reasons"])

    assert drain_lineage_queue() >= 1
    lineage = client.get(f"/performance/lineage/{body['calculation_id']}").json()
    assert "SI_attribution_supportability_evidence.csv" in lineage["artifacts"]


def test_attribution_endpoint_hierarchical(client):
    """Tests multi-level hierarchical attribution, ensuring bottom-up aggregation is correct."""
    payload = {
        "portfolio_id": "HIERARCHY_01",
        "mode": "by_instrument",
        "group_by": ["assetClass", "sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"assetClass": "Equity", "sector": "Tech"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408}],
            },
            {
                "instrument_id": "JNJ",
                "meta": {"assetClass": "Equity", "sector": "Health"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 300, "end_mv": 303}],
            },
            {
                "instrument_id": "UST",
                "meta": {"assetClass": "Bond", "sector": "Government"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 300, "end_mv": 309}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"assetClass": "Equity", "sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.4}],
            },
            {
                "key": {"assetClass": "Equity", "sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.3}],
            },
            {
                "key": {"assetClass": "Bond", "sector": "Government"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.3}],
            },
        ],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["SI"]
    assert len(data["levels"]) == 2
    level_ac = data["levels"][0]
    level_sector = data["levels"][1]
    _assert_authoritative_level_totals(level_ac)
    _assert_authoritative_level_totals(level_sector)
    equity_ac_effects = next(g for g in level_ac["groups"] if g["key"]["assetClass"] == "Equity")
    tech_sector_effects = next(g for g in level_sector["groups"] if g["key"]["sector"] == "Tech")
    health_sector_effects = next(g for g in level_sector["groups"] if g["key"]["sector"] == "Health")
    assert equity_ac_effects["allocation"] == pytest.approx(
        tech_sector_effects["allocation"] + health_sector_effects["allocation"]
    )
    assert equity_ac_effects["selection"] == pytest.approx(
        tech_sector_effects["selection"] + health_sector_effects["selection"]
    )


def test_attribution_endpoint_supports_explicit_period_windows(client):
    payload = {
        "portfolio_id": "ATTRIB_EXPLICIT_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-02",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [
                    {"date": "2025-01-01", "return_base": 0.10, "weight_bop": 1.0},
                    {"date": "2025-01-02", "return_base": 0.01, "weight_bop": 1.0},
                    {"date": "2025-01-03", "return_base": 0.01, "weight_bop": 1.0},
                ],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [
                    {"date": "2025-01-01", "return_base": 0.10, "weight_bop": 1.0},
                    {"date": "2025-01-02", "return_base": 0.01, "weight_bop": 1.0},
                    {"date": "2025-01-03", "return_base": 0.01, "weight_bop": 1.0},
                ],
            }
        ],
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    assert set(response.json()["results_by_period"]) == {"EXPLICIT"}


@pytest.mark.parametrize("decimal_strings", [False, True])
def test_attribution_endpoint_currency_attribution(client, decimal_strings):
    """Tests the Karnosky-Singer currency attribution model end-to-end."""
    payload = {
        "portfolio_id": "FX_ATTRIB_01",
        "mode": "by_instrument",
        "group_by": ["currency"],
        "linking": "none",
        "frequency": "daily",
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "GROSS",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 103.02}],
        },
        "instruments_data": [
            {
                "instrument_id": "EUR_ASSET",
                "meta": {"currency": "EUR"},
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0}
                ],  # 2% local return
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"currency": "EUR"},
                "observations": [
                    {
                        "date": "2025-01-01",
                        "weight_bop": 1.0,
                        "return_local": 0.015,  # 1.5% local return
                        "return_fx": 0.01,  # 1% fx return
                        "return_base": 0.02515,  # (1.015 * 1.01) - 1
                    }
                ],
            }
        ],
        "fx": {
            "rates": [
                {"date": "2024-12-31", "ccy": "EUR", "rate": 1.00},
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.01},  # 1% fx return
            ]
        },
    }
    if decimal_strings:
        for rate in payload["fx"]["rates"]:
            rate["rate"] = str(rate["rate"])
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["SI"]

    assert "currency_attribution" in data
    assert data["currency_attribution"] is not None
    eur_effects = data["currency_attribution"][0]["effects"]

    assert eur_effects["local_allocation"] == pytest.approx(0.0)
    assert eur_effects["local_selection"] == pytest.approx(0.5)
    assert eur_effects["currency_allocation"] == pytest.approx(0.0)
    assert eur_effects["currency_selection"] == pytest.approx(0.005)
    assert eur_effects["total_effect"] == pytest.approx(0.505)
    totals = data["currency_attribution_totals"]
    assert totals["local_allocation"] == pytest.approx(0.0)
    assert totals["local_selection"] == pytest.approx(0.5)
    assert totals["currency_allocation"] == pytest.approx(0.0)
    assert totals["currency_selection"] == pytest.approx(0.005)
    assert totals["total_effect"] == pytest.approx(0.505)
    assert totals["currency_count"] == 1

    calculation_id = response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1
    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200
    lineage_data = lineage_response.json()
    assert "SI_currency_attribution_effects.csv" in lineage_data["artifacts"]


def test_by_group_currency_attribution_publishes_source_preconverted_evidence(client):
    payload = {
        "portfolio_id": "FX_GROUP_ATTRIB_01",
        "mode": "by_group",
        "group_by": ["currency"],
        "linking": "none",
        "frequency": "daily",
        "currency": "USD",
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"currency": "EUR"},
                "observations": [
                    {
                        "date": "2025-01-01",
                        "weight_bop": 1.0,
                        "return_local": 0.02,
                        "return_fx": 0.01,
                        "return_base": 0.0302,
                    }
                ],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"currency": "EUR"},
                "observations": [
                    {
                        "date": "2025-01-01",
                        "weight_bop": 1.0,
                        "return_local": 0.015,
                        "return_fx": 0.01,
                        "return_base": 0.02515,
                    }
                ],
            }
        ],
        "fx": {"rates": []},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    evidence = response.json()["currency_evidence"]
    assert evidence == {
        "portfolio_base_currency": "USD",
        "requested_report_ccy": "USD",
        "applied_report_ccy": "USD",
        "restated": True,
        "currency_mode_applied": "BOTH",
        "fx_source": "source_preconverted",
        "fx_coverage": "complete",
        "fixing_policy": "SOURCE_PRECONVERTED_RETURN_COMPONENTS",
        "applied_pairs": ["EUR/USD"],
        "reason": "SOURCE_PRECONVERTED_GROUP_RETURNS_APPLIED",
    }

    payload["portfolio_groups_data"][0]["observations"][0].pop("return_fx")
    incomplete = client.post("/performance/attribution", json=payload)
    assert incomplete.status_code == 422
    assert incomplete.json()["error_code"] == "FX_SOURCE_PRECONVERTED_EVIDENCE_REQUIRED"

    payload["portfolio_groups_data"][0]["observations"][0]["return_fx"] = 0.01
    payload["report_ccy"] = "SGD"
    unapplied_report_currency = client.post("/performance/attribution", json=payload)
    assert unapplied_report_currency.status_code == 422
    assert unapplied_report_currency.json()["error_code"] == "FX_SOURCE_PRECONVERTED_REPORT_CURRENCY_MISMATCH"


@pytest.mark.parametrize(
    "error_class, expected_status",
    [
        (InvalidEngineInputError, 400),
        (EngineCalculationError, 500),
        (ValueError, 400),
        (NotImplementedError, 400),
        (Exception, 500),
    ],
)
def test_attribution_endpoint_error_handling(client, mocker, error_class, expected_status):
    """Tests that the attribution endpoint correctly handles engine exceptions."""
    mocker.patch("app.services.attribution_service.run_attribution_calculations", side_effect=error_class("Test Error"))
    payload = {
        "portfolio_id": "ERROR",
        "mode": "by_group",
        "group_by": ["sector"],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == expected_status
    assert "detail" in response.json()


def test_attribution_endpoint_returns_400_when_no_resolved_periods(client, mocker):
    """Tests explicit 400 path when period resolution yields no valid periods."""
    mocker.patch("app.services.attribution_service.resolve_periods", return_value=[])
    payload = {
        "portfolio_id": "ATTRIB_NO_PERIODS",
        "mode": "by_group",
        "group_by": ["sector"],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "SI", "frequencies": ["monthly"]}],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "No valid periods could be resolved."


def test_attribution_endpoint_skips_empty_period_slice(client, mocker):
    """Tests empty-slice branch where a resolved period has no matching effect rows."""
    mocker.patch(
        "app.services.attribution_service.resolve_periods",
        return_value=[
            ResolvedPeriod(name="SI", start_date="2025-01-01", end_date="2025-01-31"),
            ResolvedPeriod(name="MTD", start_date="2025-02-01", end_date="2025-02-28"),
        ],
    )
    payload = {
        "portfolio_id": "ATTRIB_EMPTY_SLICE",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [
            {"period": "SI", "frequencies": ["monthly"]},
            {"period": "MTD", "frequencies": ["monthly"]},
        ],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.02, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    results = response.json()["results_by_period"]
    assert "SI" in results
    assert "MTD" not in results


def test_attribution_async_result_retrieval(client):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    payload = {
        "portfolio_id": "ATTRIB_ASYNC_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }

    try:
        accepted = client.post("/performance/attribution", json=payload)
        assert accepted.status_code == 202
        calculation_id = accepted.json()["calculation_id"]

        pending = client.get(f"/performance/attribution/results/{calculation_id}")
        assert pending.status_code == 202

        assert drain_compute_queue() == 1

        complete = client.get(f"/performance/attribution/results/{calculation_id}")
        assert complete.status_code == 200
        assert complete.json()["calculation_id"] == calculation_id
        assert complete.json()["meta"]["precision_mode"] == "FLOAT64"
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold


def test_attribution_supports_stateful_input_mode(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1018.5",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1018.5",
                        "ending_market_value": "1028.67",
                    },
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "600",
                        "ending_market_value_portfolio_currency": "612",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "400",
                        "ending_market_value_portfolio_currency": "406.5",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "612",
                        "ending_market_value_portfolio_currency": "618.12",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "406.5",
                        "ending_market_value_portfolio_currency": "410.55",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    },
                    {
                        "index_id": "IDX_2",
                        "classification_labels": {"sector": "Healthcare"},
                    },
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.015,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.02,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_id"] == "ATTRIB_STATEFUL"
    assert body["input_mode"] == "stateful"
    assert body["benchmark_context"] == {
        "benchmark_id": "BMK_1",
        "return_source": "calculated",
    }
    itd = body["results_by_period"]["SI"]
    assert itd["reconciliation"]["total_active_return"] == pytest.approx(1.0985232695139984)
    assert itd["reconciliation"]["sum_of_effects"] == pytest.approx(1.0985232695139984)
    assert itd["status"] == "partial"
    assert "off_benchmark_exposure" in itd["reason_codes"]
    assert itd["supportability_evidence"]["portfolio_only_group_count"] == 2
    assert itd["supportability_evidence"]["benchmark_only_group_count"] == 0
    level = itd["levels"][0]
    tech_group = next(group for group in level["groups"] if group["key"]["sector"] == "technology")
    assert tech_group["selection"] == pytest.approx(0.25)


def test_attribution_stateful_converts_non_base_cash_flows_using_explicit_fx_metadata(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "132",
                        "ending_market_value": "145.2",
                        "cash_flows": [{"amount": "13.2", "timing": "bod", "cash_flow_type": "external_flow"}],
                    }
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_EUR_1",
                        "security_id": "SEC_EUR_1",
                        "valuation_date": "2025-01-01",
                        "position_currency": "EUR",
                        "cash_flow_currency": "EUR",
                        "position_to_portfolio_fx_rate": "1.20",
                        "portfolio_to_reporting_fx_rate": "1.10",
                        "beginning_market_value_reporting_currency": "132",
                        "ending_market_value_reporting_currency": "145.2",
                        "beginning_market_value_portfolio_currency": "120",
                        "ending_market_value_portfolio_currency": "132",
                        "beginning_market_value_position_currency": "100",
                        "ending_market_value_position_currency": "110",
                        "cash_flows": [{"amount": "10", "timing": "bod", "cash_flow_type": "external_flow"}],
                        "dimensions": {"sector": "Technology"},
                    }
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=1.0,
            component_return=0.0,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_FX_CF",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    itd = response.json()["results_by_period"]["SI"]
    assert itd["reconciliation"]["total_active_return"] == pytest.approx(0.0)
    assert itd["reconciliation"]["sum_of_effects"] == pytest.approx(0.0)


def test_attribution_stateful_rejects_acquisition_day_rows_without_cash_flow_semantics(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1018.5",
                    },
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "0",
                        "ending_market_value_portfolio_currency": "600",
                        "cash_flows": [],
                        "dimensions": {"asset_class": "Equity"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "600",
                        "ending_market_value_portfolio_currency": "606",
                        "cash_flows": [],
                        "dimensions": {"asset_class": "Equity"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {"index_id": "IDX_1", "classification_labels": {"asset_class": "Equity"}},
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=1.0,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 2),
            weight_bop=1.0,
            component_return=0.01,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_GAP",
        "mode": "by_instrument",
        "group_by": ["asset_class"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 422
    assert "cannot safely compute acquisition-day position returns" in response.json()["detail"]


def test_attribution_stateful_rejects_portfolio_position_alignment_mismatch(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "900",
                        "ending_market_value_portfolio_currency": "909",
                        "cash_flows": [],
                        "dimensions": {"asset_class": "Equity"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (200, {"records": [{"index_id": "IDX_1", "classification_labels": {"asset_class": "Equity"}}]})

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=1.0,
            component_return=0.01,
        ),
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_MISMATCH",
        "mode": "by_instrument",
        "group_by": ["asset_class"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 503
    assert "portfolio timeseries does not align with summed position timeseries" in response.json()["detail"]


def test_attribution_stateful_offloads_on_resolved_input_count(client, monkeypatch):
    original_window_threshold = settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS = 30
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 2

    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1010",
                        "ending_market_value": "1020.1",
                    },
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "600",
                        "ending_market_value_portfolio_currency": "606",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "606",
                        "ending_market_value_portfolio_currency": "612.06",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "400",
                        "ending_market_value_portfolio_currency": "404",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "404",
                        "ending_market_value_portfolio_currency": "408.04",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {"index_id": "IDX_1", "classification_labels": {"sector": "Technology"}},
                    {"index_id": "IDX_2", "classification_labels": {"sector": "Healthcare"}},
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 2),
            weight_bop=0.5,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.015,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 2),
            weight_bop=0.5,
            component_return=0.015,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_ASYNC",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        accepted = client.post("/performance/attribution", json=payload)

        assert accepted.status_code == 202
        calculation_id = UUID(accepted.json()["calculation_id"])
        execution = execution_registry.get_execution(calculation_id)
        assert execution is not None
        assert execution.requested_window["input_count"] == 4
        assert execution.requested_window["input_mode"] == "stateful"
        assert execution.requested_window["benchmark_id"] == "BMK_1"
        assert execution.requested_window["benchmark_return_source"] == "calculated"
        job = compute_job_store.get_job(calculation_id)
        assert job is not None
        assert "stateful_input" not in job.request_payload["resolved_request"]
        assert "benchmark_groups_data" in job.request_payload["resolved_request"]
        assert job.request_payload["resolved_benchmark_id"] == "BMK_1"
        assert job.request_payload["resolved_benchmark_return_source"] == "calculated"

        assert drain_compute_queue() == 1

        complete = client.get(f"/performance/attribution/results/{calculation_id}")
        assert complete.status_code == 200
        body = complete.json()
        assert body["input_mode"] == "stateful"
        assert body["benchmark_context"] == {
            "benchmark_id": "BMK_1",
            "return_source": "calculated",
        }
    finally:
        settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_attribution_stateful_promoted_async_replays_identical_retry(client, monkeypatch):
    original_window_threshold = settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS = 30
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 2

    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "600",
                        "ending_market_value_portfolio_currency": "606",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "606",
                        "ending_market_value_portfolio_currency": "612.06",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "400",
                        "ending_market_value_portfolio_currency": "404",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                    {
                        "position_id": "POS_2",
                        "security_id": "SEC_2",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "404",
                        "ending_market_value_portfolio_currency": "408.04",
                        "cash_flows": [],
                        "dimensions": {"sector": "Healthcare"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {"index_id": "IDX_1", "classification_labels": {"sector": "Technology"}},
                    {"index_id": "IDX_2", "classification_labels": {"sector": "Healthcare"}},
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 2),
            weight_bop=0.5,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.015,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            perf_date=date(2025, 1, 2),
            weight_bop=0.5,
            component_return=0.015,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "ATTRIB_STATEFUL_ASYNC_REPLAY",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    try:
        first = client.post("/performance/attribution", json=payload)
        second = client.post("/performance/attribution", json=payload)

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["calculation_id"] == payload["calculation_id"]
        assert second.json()["calculation_id"] == payload["calculation_id"]
    finally:
        settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_attribution_stateful_currency_mode_both_supports_mixed_currency_decomposition(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "200",
                        "ending_market_value": "205.111",
                    },
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_EUR",
                        "security_id": "SEC_EUR",
                        "position_currency": "EUR",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_reporting_currency": "110",
                        "ending_market_value_reporting_currency": "113.311",
                        "beginning_market_value_position_currency": "100",
                        "ending_market_value_position_currency": "101",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology", "country": "DE"},
                    },
                    {
                        "position_id": "POS_USD",
                        "security_id": "SEC_USD",
                        "position_currency": "USD",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_reporting_currency": "90",
                        "ending_market_value_reporting_currency": "91.8",
                        "beginning_market_value_position_currency": "90",
                        "ending_market_value_position_currency": "91.8",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology", "country": "US"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    },
                    {
                        "index_id": "IDX_2",
                        "classification_labels": {"sector": "Technology"},
                    },
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            component_currency="EUR",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.0302,
            component_return_local=0.02,
            component_return_fx=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_2",
            component_currency="USD",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.02,
            component_return_local=0.02,
            component_return_fx=0.0,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL",
        "mode": "by_instrument",
        "group_by": ["currency"],
        "linking": "none",
        "frequency": "daily",
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "fx": {
            "rates": [
                {"date": "2024-12-31", "ccy": "EUR", "rate": 1.10},
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.111},
            ]
        },
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload, headers={"X-Tenant-Id": "tenant-a"})

    assert response.status_code == 200
    body = response.json()
    assert body["input_mode"] == "stateful"
    assert body["diagnostics"]["samples"]["period_status_counts"] == [{"valid": 1}]
    assert body["audit"]["counts"]["benchmark_context_count"] == 1
    currency_results = body["results_by_period"]["SI"]["currency_attribution"]
    assert currency_results is not None
    by_currency = {entry["currency"]: entry for entry in currency_results}
    assert by_currency["eur"]["weight_portfolio_avg"] == pytest.approx(55.0)
    assert by_currency["usd"]["weight_portfolio_avg"] == pytest.approx(45.0)
    assert body["results_by_period"]["SI"]["currency_attribution_totals"]["currency_count"] == 2
    assert body["currency_evidence"]["applied_report_ccy"] == "USD"
    assert body["currency_evidence"]["applied_pairs"] == ["EUR/USD"]
    assert body["currency_evidence"]["restated"] is True
    assert body["currency_evidence"]["fx_coverage"] == "complete"

    payload["fx"] = {}
    rejected = client.post("/performance/attribution", json=payload, headers={"X-Tenant-Id": "tenant-a"})
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "FX_RATES_REQUIRED"
    assert "fx.rates" in rejected.json()["detail"]
    assert "EUR/USD" in rejected.json()["detail"]

    payload["fx"] = {"rates": [{"date": "2024-12-31", "ccy": "EUR", "rate": 1.10}]}
    partial = client.post("/performance/attribution", json=payload, headers={"X-Tenant-Id": "tenant-a"})
    assert partial.status_code == 422
    assert "EUR/USD dates 2025-01-01" in partial.json()["detail"]


def test_attribution_stateful_hashes_follow_resolved_inputs(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1010",
                        "ending_market_value": "1020.1",
                    },
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "1000",
                        "ending_market_value_portfolio_currency": "1010",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "1010",
                        "ending_market_value_portfolio_currency": "1020.1",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    _patch_stateful_attribution_benchmark_input(
        monkeypatch,
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 1),
            weight_bop=1.0,
            component_return=0.01,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_1",
            perf_date=date(2025, 1, 2),
            weight_bop=1.0,
            component_return=0.01,
        ),
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_HASH",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    body = response.json()
    resolved = asyncio.run(
        resolve_attribution_request(
            AttributionAnalyticsRequest.model_validate(
                {
                    **payload,
                    "calculation_id": body["calculation_id"],
                }
            ),
            settings=settings,
        )
    )
    expected_input_fingerprint, expected_calculation_hash = generate_canonical_hash(
        resolved.attribution_request,
        calculation_engine_version(settings),
    )

    assert body["meta"]["input_fingerprint"] == expected_input_fingerprint
    assert body["meta"]["calculation_hash"] == expected_calculation_hash


def test_attribution_async_result_not_found_and_failed(client, mocker):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    original_attempts = settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = 1
    payload = {
        "portfolio_id": "ATTRIB_ASYNC_FAIL_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    mocker.patch("app.workers.compute_executor_worker.calculate_attribution", side_effect=RuntimeError("explode"))

    try:
        missing = client.get("/performance/attribution/results/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404

        accepted = client.post("/performance/attribution", json=payload)
        assert accepted.status_code == 202
        calculation_id = accepted.json()["calculation_id"]

        assert drain_compute_queue() == 1

        failed = client.get(f"/performance/attribution/results/{calculation_id}")
        assert failed.status_code == 409
        assert (
            failed.json()["detail"] == "Compute job execution failed unexpectedly. Use the correlation_id for support."
        )
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold
        settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = original_attempts


def test_attribution_async_duplicate_submission_replays_same_request(client):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    calculation_id = str(uuid4())
    payload = {
        "calculation_id": calculation_id,
        "portfolio_id": "ATTRIB_ASYNC_REPLAY_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }

    try:
        first = client.post("/performance/attribution", json=payload)
        second = client.post("/performance/attribution", json=payload)

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["calculation_id"] == calculation_id
        assert second.json()["calculation_id"] == calculation_id
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold


def test_attribution_async_duplicate_submission_conflicts_on_payload_drift(client):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    calculation_id = str(uuid4())
    first_payload = {
        "calculation_id": calculation_id,
        "portfolio_id": "ATTRIB_ASYNC_CONFLICT_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    second_payload = {**first_payload, "group_by": ["currency"]}

    try:
        first = client.post("/performance/attribution", json=first_payload)
        second = client.post("/performance/attribution", json=second_payload)

        assert first.status_code == 202
        assert second.status_code == 409
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold


def _idempotent_attribution_payload(*, calculation_id: str, portfolio_id: str) -> dict:
    return {
        "calculation_id": calculation_id,
        "portfolio_id": portfolio_id,
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }


def test_attribution_idempotency_key_replays_original_handle_across_client_restart(client):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 100_000
    first_calculation_id = str(uuid4())
    retry_calculation_id = str(uuid4())
    payload = _idempotent_attribution_payload(
        calculation_id=first_calculation_id,
        portfolio_id="ATTRIB_IDEMPOTENT_REPLAY_01",
    )
    headers = {"X-Tenant-Id": "tenant-a", "Idempotency-Key": "gateway-attribution-window-001"}

    try:
        first = client.post("/performance/attribution", json=payload, headers=headers)
        # A fresh HTTP client models the caller losing the accepted response context after
        # cancellation or timeout. Durable identity, rather than client-local state, resumes it.
        with TestClient(app) as restarted_client:
            retry = restarted_client.post(
                "/performance/attribution",
                json={**payload, "calculation_id": retry_calculation_id},
                headers=headers,
            )

        assert first.status_code == 202
        assert retry.status_code == 202
        assert first.json()["state"] == "accepted"
        assert retry.json()["state"] == "accepted"
        assert first.json()["calculation_id"] == first_calculation_id
        assert retry.json()["calculation_id"] == first_calculation_id
        assert compute_job_store.get_job(UUID(retry_calculation_id)) is None
        with execution_registry._engine.connect() as connection:
            retained = (
                connection.execute(
                    text(
                        "SELECT submission_idempotency_key_hash, submission_identity_fingerprint, "
                        "submission_contract_version, request_json FROM analytics_execution "
                        "WHERE calculation_id = :calculation_id"
                    ),
                    {"calculation_id": first_calculation_id},
                )
                .mappings()
                .one()
            )
        assert retained["submission_idempotency_key_hash"] != headers["Idempotency-Key"]
        assert len(retained["submission_idempotency_key_hash"]) == 64
        assert retained["submission_identity_fingerprint"].startswith("sha256:")
        assert retained["submission_contract_version"] == "attribution-submission-v1"
        assert headers["Idempotency-Key"] not in retained["request_json"]
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold


def test_attribution_idempotency_key_replays_across_engine_version_upgrade(client):
    original_engine_version = settings.CALCULATION_ENGINE_VERSION
    first_calculation_id = str(uuid4())
    retry_calculation_id = str(uuid4())
    payload = _idempotent_attribution_payload(
        calculation_id=first_calculation_id,
        portfolio_id="ATTRIB_IDEMPOTENT_ENGINE_UPGRADE_01",
    )
    headers = {"X-Tenant-Id": "tenant-a", "Idempotency-Key": "gateway-attribution-engine-upgrade-001"}

    try:
        first = client.post("/performance/attribution", json=payload, headers=headers)
        settings.CALCULATION_ENGINE_VERSION = f"{original_engine_version}-successor"
        retry = client.post(
            "/performance/attribution",
            json={**payload, "calculation_id": retry_calculation_id},
            headers=headers,
        )

        assert first.status_code == 202
        assert retry.status_code == 202
        assert retry.json()["calculation_id"] == first_calculation_id
        assert compute_job_store.get_job(UUID(retry_calculation_id)) is None
    finally:
        settings.CALCULATION_ENGINE_VERSION = original_engine_version


def test_attribution_idempotency_replay_repairs_crash_interrupted_submission_stage(client):
    first_calculation_id = str(uuid4())
    retry_calculation_id = str(uuid4())
    payload = _idempotent_attribution_payload(
        calculation_id=first_calculation_id,
        portfolio_id="ATTRIB_IDEMPOTENT_STAGE_REPAIR_01",
    )
    headers = {"X-Tenant-Id": "tenant-a", "Idempotency-Key": "gateway-attribution-stage-repair-001"}

    first = client.post("/performance/attribution", json=payload, headers=headers)
    assert first.status_code == 202
    execution_registry.start_stage(UUID(first_calculation_id), EXECUTION_STAGE_SUBMISSION)

    retry = client.post(
        "/performance/attribution",
        json={**payload, "calculation_id": retry_calculation_id},
        headers=headers,
    )
    retained = execution_registry.get_execution(UUID(first_calculation_id))

    assert retry.status_code == 202
    assert retry.json()["calculation_id"] == first_calculation_id
    assert retained is not None
    submission_stage = next(stage for stage in retained.stages if stage.stage_name == EXECUTION_STAGE_SUBMISSION)
    assert submission_stage.status == ExecutionStageStatus.COMPLETE
    assert submission_stage.details == {"offload_reason": "caller_idempotency_key"}
    assert compute_job_store.get_job(UUID(retry_calculation_id)) is None


def test_attribution_idempotency_key_rejects_changed_material_payload(client):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    payload = _idempotent_attribution_payload(
        calculation_id=str(uuid4()),
        portfolio_id="ATTRIB_IDEMPOTENT_CONFLICT_01",
    )
    headers = {"X-Tenant-Id": "tenant-a", "Idempotency-Key": "gateway-attribution-window-002"}

    try:
        first = client.post("/performance/attribution", json=payload, headers=headers)
        conflict = client.post(
            "/performance/attribution",
            json={**payload, "calculation_id": str(uuid4()), "group_by": ["currency"]},
            headers=headers,
        )

        assert first.status_code == 202
        assert conflict.status_code == 409
        assert conflict.json()["error_code"] == "ATTRIBUTION_IDEMPOTENCY_CONFLICT"
        assert conflict.json()["retryable"] is False
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold


def test_attribution_new_idempotency_key_cannot_alias_an_existing_calculation_id(client):
    calculation_id = str(uuid4())
    payload = _idempotent_attribution_payload(
        calculation_id=calculation_id,
        portfolio_id="ATTRIB_IDEMPOTENT_IDENTITY_ALIAS_01",
    )
    first = client.post(
        "/performance/attribution",
        json=payload,
        headers={"X-Tenant-Id": "tenant-a", "Idempotency-Key": "gateway-attribution-original-key"},
    )
    alias = client.post(
        "/performance/attribution",
        json=payload,
        headers={"X-Tenant-Id": "tenant-a", "Idempotency-Key": "gateway-attribution-alias-key"},
    )

    assert first.status_code == 202
    assert alias.status_code == 409
    assert alias.json()["error_code"] == "ATTRIBUTION_IDEMPOTENCY_CONFLICT"
    assert alias.json()["retryable"] is False
    assert compute_job_store.get_job(UUID(calculation_id)) is not None
    with execution_registry._engine.connect() as connection:
        execution_count = connection.execute(text("SELECT COUNT(*) FROM analytics_execution")).scalar_one()
    assert execution_count == 1


def test_attribution_idempotency_key_requires_tenant_authority_before_acceptance(client):
    calculation_id = str(uuid4())
    payload = _idempotent_attribution_payload(
        calculation_id=calculation_id,
        portfolio_id="ATTRIB_IDEMPOTENT_AUTHORITY_01",
    )

    with TestClient(app) as tenantless_client:
        response = tenantless_client.post(
            "/performance/attribution",
            json=payload,
            headers={"Idempotency-Key": "gateway-attribution-authority-001"},
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "TENANT_AUTHORITY_REQUIRED"
    assert execution_registry.get_execution(UUID(calculation_id)) is None
    assert compute_job_store.get_job(UUID(calculation_id)) is None


def test_attribution_idempotency_key_rejects_whitespace_before_acceptance(client):
    calculation_id = str(uuid4())
    response = client.post(
        "/performance/attribution",
        json=_idempotent_attribution_payload(
            calculation_id=calculation_id,
            portfolio_id="ATTRIB_IDEMPOTENT_KEY_INVALID",
        ),
        headers={"X-Tenant-Id": "tenant-a", "Idempotency-Key": "   "},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ATTRIBUTION_IDEMPOTENCY_KEY_INVALID"
    assert execution_registry.get_execution(UUID(calculation_id)) is None
    assert compute_job_store.get_job(UUID(calculation_id)) is None


def test_attribution_idempotency_key_namespace_is_tenant_scoped(client):
    first_calculation_id = str(uuid4())
    second_calculation_id = str(uuid4())
    key = "gateway-attribution-tenant-scope-001"
    first = client.post(
        "/performance/attribution",
        json=_idempotent_attribution_payload(
            calculation_id=first_calculation_id,
            portfolio_id="ATTRIB_IDEMPOTENT_TENANT_A",
        ),
        headers={"X-Tenant-Id": "tenant-a", "Idempotency-Key": key},
    )
    second = client.post(
        "/performance/attribution",
        json=_idempotent_attribution_payload(
            calculation_id=second_calculation_id,
            portfolio_id="ATTRIB_IDEMPOTENT_TENANT_A",
        ),
        headers={"X-Tenant-Id": "tenant-b", "Idempotency-Key": key},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["calculation_id"] == first_calculation_id
    assert second.json()["calculation_id"] == second_calculation_id
    assert execution_registry.get_execution(UUID(first_calculation_id)).tenant_id == "tenant-a"
    assert execution_registry.get_execution(UUID(second_calculation_id)).tenant_id == "tenant-b"


def test_attribution_completed_idempotent_replay_returns_original_result_without_reexecution(client):
    first_calculation_id = str(uuid4())
    retry_calculation_id = str(uuid4())
    payload = _idempotent_attribution_payload(
        calculation_id=first_calculation_id,
        portfolio_id="ATTRIB_IDEMPOTENT_COMPLETE_01",
    )
    headers = {"X-Tenant-Id": "tenant-a", "Idempotency-Key": "gateway-attribution-complete-001"}

    first = client.post("/performance/attribution", json=payload, headers=headers)
    assert first.status_code == 202
    assert drain_compute_queue() == 1
    assert drain_lineage_queue() >= 1
    original_result = client.get(first.json()["result_path"], headers={"X-Tenant-Id": "tenant-a"})
    assert original_result.status_code == 200
    assert original_result.json()["meta"]["precision_mode"] == "FLOAT64"
    assert compute_job_store.prune_terminal_jobs_older_than(datetime.now(timezone.utc) + timedelta(seconds=1)) == 1
    assert async_result_store.prune_results_older_than(datetime.now(timezone.utc) + timedelta(seconds=1)) == 1
    assert compute_job_store.get_job(UUID(first_calculation_id)) is None
    assert async_result_store.get_result(UUID(first_calculation_id)) is None

    replay = client.post(
        "/performance/attribution",
        json={**payload, "calculation_id": retry_calculation_id},
        headers=headers,
    )
    result = client.get(first.json()["result_path"], headers={"X-Tenant-Id": "tenant-a"})
    foreign_status = client.get(first.json()["poll_path"], headers={"X-Tenant-Id": "tenant-b"})
    foreign_result = client.get(first.json()["result_path"], headers={"X-Tenant-Id": "tenant-b"})

    assert replay.status_code == 202
    assert replay.json()["calculation_id"] == first_calculation_id
    assert drain_compute_queue() == 0
    assert result.status_code == 200
    assert result.json()["calculation_id"] == first_calculation_id
    assert result.json() == original_result.json()
    refused = client.post(
        "/performance/attribution",
        json={**payload, "precision_mode": "DECIMAL_STRICT"},
        headers=headers,
    )
    assert refused.status_code == 422
    assert client.get(first.json()["result_path"], headers={"X-Tenant-Id": "tenant-a"}).json() == original_result.json()
    assert foreign_status.status_code == 403
    assert foreign_result.status_code == 403
    assert foreign_status.json()["reason"] == "result_tenant_authority_mismatch"
    assert foreign_result.json()["reason"] == "result_tenant_authority_mismatch"
    assert compute_job_store.get_job(UUID(retry_calculation_id)) is None


def test_attribution_retained_legacy_precision_metadata_is_not_rewritten_on_retrieval(client):
    payload = _single_period_sector_attribution_payload(model="BF", portfolio_weights=(0.6, 0.4))
    calculation_id = uuid4()
    payload["calculation_id"] = str(calculation_id)
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    assert drain_lineage_queue() >= 1
    # Explicit historical fixture: old metadata could report strict although the engine
    # executed FLOAT64. Retrieval preserves reported evidence, never certifies or repairs it.
    historical = response.json()
    historical["meta"]["precision_mode"] = "DECIMAL_STRICT"
    historical["meta"]["engine_version"] = "lotus-performance-calculation-engine.v15"
    execution_registry.retain_response_payload(calculation_id, response_payload=historical)
    result = client.get(f"/performance/attribution/results/{calculation_id}")
    assert result.status_code == 200
    assert result.json() == historical
    assert execution_registry.get_execution(calculation_id).response_payload == historical
    assert compute_job_store.get_job(calculation_id) is None


def test_attribution_compute_complete_idempotent_replay_does_not_requeue_while_lineage_is_pending(client):
    first_calculation_id = str(uuid4())
    retry_calculation_id = str(uuid4())
    payload = _idempotent_attribution_payload(
        calculation_id=first_calculation_id,
        portfolio_id="ATTRIB_IDEMPOTENT_LINEAGE_PENDING_01",
    )
    headers = {"X-Tenant-Id": "tenant-a", "Idempotency-Key": "gateway-attribution-lineage-pending-001"}

    first = client.post("/performance/attribution", json=payload, headers=headers)
    assert first.status_code == 202
    assert drain_compute_queue() == 1
    retained_execution = execution_registry.get_execution(UUID(first_calculation_id))
    assert retained_execution is not None
    assert retained_execution.status == ExecutionStatus.RUNNING
    assert retained_execution.response_payload is not None
    assert compute_job_store.prune_terminal_jobs_older_than(datetime.now(timezone.utc) + timedelta(seconds=1)) == 1

    replay = client.post(
        "/performance/attribution",
        json={**payload, "calculation_id": retry_calculation_id},
        headers=headers,
    )

    assert replay.status_code == 202
    assert replay.json()["calculation_id"] == first_calculation_id
    assert drain_compute_queue() == 0
    assert compute_job_store.get_job(UUID(retry_calculation_id)) is None
