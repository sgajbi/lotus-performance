from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pandas as pd

from app.api.endpoints.contribution import _should_offload_contribution
from app.api.endpoints.performance import _should_offload_attribution
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest
from app.models.attribution_requests import AttributionRequest
from app.models.contribution_requests import ContributionRequest
from app.services import attribution_service, contribution_service
from common.enums import AttributionModel, LinkingMethod, PeriodType


def test_should_offload_contribution_uses_runtime_settings(mocker):
    request = ContributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                ],
            },
            "positions_data": [{"position_id": "A", "valuation_points": []}],
        }
    )
    mocker.patch(
        "app.api.endpoints.contribution.get_settings",
        return_value=type("Settings", (), {"CONTRIBUTION_EXECUTOR_POSITION_COUNT": 1})(),
    )

    assert _should_offload_contribution(request) is True


def test_should_offload_attribution_uses_runtime_settings(mocker):
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "mode": "by_group",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
    )
    mocker.patch(
        "app.api.endpoints.performance.get_settings",
        return_value=type("Settings", (), {"ATTRIBUTION_EXECUTOR_INPUT_COUNT": 2, "APP_VERSION": "unused"})(),
    )

    assert _should_offload_attribution(request) is True


def test_should_offload_stateful_attribution_uses_window_runtime_settings(mocker):
    request = AttributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "P1",
            "mode": "by_instrument",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-07-31",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    mocker.patch(
        "app.api.endpoints.performance.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "ATTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "ATTRIBUTION_EXECUTOR_INPUT_COUNT": 999,
                "APP_VERSION": "unused",
            },
        )(),
    )

    assert _should_offload_attribution(request) is True


def test_contribution_service_uses_runtime_app_version(mocker):
    captured: dict[str, object] = {}
    mocker.patch(
        "app.services.contribution_service.get_settings",
        return_value=type("Settings", (), {"APP_VERSION": "runtime-version"})(),
    )
    mocker.patch.object(contribution_service.execution_registry, "mark_running", lambda calculation_id: None)
    mocker.patch.object(
        contribution_service.execution_registry,
        "start_stage",
        lambda calculation_id, stage_name: None,
    )
    mocker.patch(
        "app.services.contribution_service.resolve_periods",
        return_value=[
            SimpleNamespace(
                name="ITD",
                start_date=pd.Timestamp("2025-01-01").date(),
                end_date=pd.Timestamp("2025-01-02").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame({"position_id": ["A"]}),
            pd.DataFrame(
                {
                    "perf_date": ["2025-01-01", "2025-01-02"],
                    "daily_ror": [1.0, 1.0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-02").date()],
                "position_id": ["A", "A"],
                "smoothed_contribution": [0.01, 0.02],
                "smoothed_local_contribution": [0.01, 0.02],
                "daily_weight": [0.5, 0.5],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: captured.update({"response_model": kwargs["response_model"]}),
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030},
                ],
            },
            "positions_data": [{"position_id": "A", "valuation_points": []}],
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    assert response.meta.engine_version == "runtime-version"
    assert captured["response_model"].meta.engine_version == "runtime-version"


def test_attribution_service_uses_runtime_app_version(mocker):
    captured: dict[str, object] = {}
    mocker.patch(
        "app.services.attribution_service.get_settings",
        return_value=type("Settings", (), {"APP_VERSION": "runtime-version"})(),
    )
    mocker.patch.object(attribution_service.execution_registry, "mark_running", lambda calculation_id: None)
    mocker.patch.object(
        attribution_service.execution_registry,
        "start_stage",
        lambda calculation_id, stage_name: None,
    )
    mocker.patch(
        "app.services.attribution_service.resolve_periods",
        return_value=[
            SimpleNamespace(
                name="ITD",
                start_date=pd.Timestamp("2025-01-01").date(),
                end_date=pd.Timestamp("2025-01-01").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    effects_df = pd.DataFrame(
        {
            "allocation": [0.1],
            "selection": [0.2],
            "interaction": [0.3],
            "total_effect": [0.6],
        },
        index=pd.MultiIndex.from_tuples([(pd.Timestamp("2025-01-01"), "Tech")], names=["date", "group"]),
    )
    mocker.patch(
        "app.services.attribution_service.run_attribution_calculations",
        return_value=(effects_df, {"effects.csv": effects_df}),
    )
    mocker.patch(
        "app.services.attribution_service.aggregate_attribution_results",
        return_value=(
            {
                "levels": [
                    {
                        "dimension": "sector",
                        "groups": [
                            {
                                "key": {"sector": "Tech"},
                                "allocation": 0.1,
                                "selection": 0.2,
                                "interaction": 0.3,
                                "total_effect": 0.6,
                            }
                        ],
                        "totals": {
                            "allocation": 0.1,
                            "selection": 0.2,
                            "interaction": 0.3,
                            "total_effect": 0.6,
                        },
                    }
                ],
                "reconciliation": {
                    "total_active_return": 0.6,
                    "sum_of_effects": 0.6,
                    "residual": 0.0,
                },
            },
            {},
        ),
    )
    mocker.patch(
        "app.services.attribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: captured.update({"response_model": kwargs["response_model"]}),
    )

    request = AttributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "model": AttributionModel.BRINSON_FACHLER.value,
            "mode": "by_group",
            "group_by": ["sector"],
            "linking": LinkingMethod.NONE.value,
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
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
    )

    response = attribution_service.calculate_attribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    assert response.meta.engine_version == "runtime-version"
    assert captured["response_model"].meta.engine_version == "runtime-version"
