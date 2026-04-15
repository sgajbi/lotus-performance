from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
from fastapi import HTTPException

from app.api.endpoints.contribution import _should_offload_contribution
from app.api.endpoints.performance import _should_offload_attribution, _should_offload_workspace_summary
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest
from app.models.attribution_requests import AttributionRequest
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import PositionContributionSeries, PositionDailyContribution
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
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


def test_should_offload_workspace_summary_uses_runtime_window_settings(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_end_date": "2026-06-30",
            "performance_start_date": "2026-01-01",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [
                {"period": "1D", "frequencies": ["daily"]},
                {"period": "1M", "frequencies": ["monthly"]},
            ],
        }
    )
    mocker.patch(
        "app.api.endpoints.performance.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS": 20,
                "WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT": 999,
            },
        )(),
    )

    assert _should_offload_workspace_summary(request) is True


def test_should_offload_workspace_summary_uses_runtime_input_count_settings(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_end_date": "2025-01-02",
            "performance_start_date": "2025-01-01",
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                ]
            },
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
        }
    )
    mocker.patch(
        "app.api.endpoints.performance.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS": 999,
                "WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT": 1,
            },
        )(),
    )

    assert _should_offload_workspace_summary(request) is True


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


def test_contribution_service_raises_when_no_periods_resolve(mocker):
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
    mocker.patch("app.services.contribution_service.resolve_periods", return_value=[])
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.contribution_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
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
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
            "positions_data": [{"position_id": "A", "valuation_points": []}],
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        contribution_service.calculate_contribution(
            request,
            input_fingerprint="fingerprint",
            calculation_hash="hash",
        )

    assert exc_info.value.status_code == 400
    assert "No valid periods could be resolved." in str(exc_info.value.detail)
    assert "No valid periods could be resolved." in str(failure_capture["message"])


def test_contribution_service_hierarchy_path_skips_empty_period_slices_and_returns_hierarchy_results(mocker):
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
                name="EMPTY",
                start_date=pd.Timestamp("2024-12-01").date(),
                end_date=pd.Timestamp("2024-12-31").date(),
                value=PeriodType.ITD,
            ),
            SimpleNamespace(
                name="ITD",
                start_date=pd.Timestamp("2025-01-01").date(),
                end_date=pd.Timestamp("2025-01-02").date(),
                value=PeriodType.ITD,
            ),
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame({"position_id": ["A", "A"]}),
            pd.DataFrame(
                {
                    "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-02").date()],
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
        "app.services.contribution_service._calculate_reset_aware_period_portfolio_return",
        return_value=0.03,
    )
    mocker.patch(
        "app.services.contribution_service._build_hierarchy_from_adjusted_position_series",
        return_value={
            "summary": {
                "portfolio_contribution": 3.0,
                "coverage_mv_pct": 100.0,
                "weighting_scheme": "average_weight",
            },
            "levels": [{"level": 1, "name": "sector", "rows": []}],
        },
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "hierarchy": ["sector"],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1030},
                ],
            },
            "positions_data": [{"position_id": "A", "valuation_points": [], "meta": {"sector": "Tech"}}],
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    assert set(response.results_by_period) == {"ITD"}
    assert response.results_by_period["ITD"].summary is not None
    assert response.results_by_period["ITD"].summary.portfolio_contribution == 3.0
    assert response.results_by_period["ITD"].summary.coverage_mv_pct == 100.0
    assert response.results_by_period["ITD"].summary.weighting_scheme == "average_weight"
    assert response.results_by_period["ITD"].levels is not None
    assert response.results_by_period["ITD"].levels[0].level == 1
    assert response.results_by_period["ITD"].levels[0].name == "sector"


def test_contribution_service_emits_average_weight_shadow_note_and_audit_count(mocker):
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
                end_date=pd.Timestamp("2025-01-04").date(),
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
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                        pd.Timestamp("2025-01-04").date(),
                    ],
                    "daily_ror": [1.0, 1.0, 1.0, 1.0],
                    "perf_reset": [0, 0, 1, 0],
                    "nip": [0, 0, 0, 1],
                    "nctrl_4": [0, 0, 0, 0],
                    "account_reset": [0, 0, 0, 0],
                    "sod_reset": [0, 0, 0, 0],
                    "nip_rule_v1_shadow": [0, 0, 0, 0],
                    "nip_rule_v2_shadow": [0, 0, 0, 0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                    pd.Timestamp("2025-01-04").date(),
                ],
                "position_id": ["A", "A", "A", "A"],
                "smoothed_contribution": [0.01, 0.01, 0.01, 0.0],
                "smoothed_local_contribution": [0.01, 0.01, 0.01, 0.0],
                "daily_weight": [0.5, 0.5, 0.3, 0.4],
                "perf_reset": [0, 0, 1, 0],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-04",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
                    {"perf_date": "2025-01-04", "begin_mv": 1030, "end_mv": 1030},
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

    period_status = response.results_by_period["ITD"].average_weight_methodology_status
    assert period_status is not None
    assert period_status.status == "BLOCKED"
    assert period_status.is_material_shadow is True
    assert period_status.is_cutover_candidate is False
    assert period_status.is_promoted is False
    assert period_status.blocker_reason_codes == ["weight_residual"]
    assert response.audit.counts["average_weight_shadow_delta_positions"] == 1
    assert response.audit.counts["average_weight_shadow_delta_max_bp"] == 1250
    assert response.audit.counts["average_weight_shadow_delta_sum_bp"] == 1250
    assert response.audit.counts["average_weight_shadow_noise_periods"] == 0
    assert response.audit.counts["average_weight_shadow_warning_periods"] == 0
    assert response.audit.counts["average_weight_shadow_material_periods"] == 1
    assert response.audit.counts["average_weight_shadow_cutover_candidate_periods"] == 0
    assert response.audit.counts["average_weight_shadow_promotion_ready_rate_bp"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_periods"] == 1
    assert response.audit.counts["average_weight_sum_residual_bp"] == 5750
    assert response.audit.counts["average_weight_shadow_blocked_by_weight_residual_periods"] == 1
    assert response.audit.counts["average_weight_shadow_blocked_by_flow_balance_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_reset_alignment_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_timeseries_delta_periods"] == 0
    assert any("Reset-aware average-weight shadow differs" in note for note in response.diagnostics.notes)
    assert any("differs materially" in note for note in response.diagnostics.notes)
    assert any("rollout readiness is currently 0 basis points" in note for note in response.diagnostics.notes)
    assert any("average weights do not sum to 100% exactly" in note for note in response.diagnostics.notes)
    assert any("did not sum cleanly to 100%" in note for note in response.diagnostics.notes)


def test_contribution_service_omits_average_weight_shadow_note_when_shadow_matches_active_mean(mocker):
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
                    "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-02").date()],
                    "daily_ror": [1.0, 1.0],
                    "perf_reset": [0, 0],
                    "nip": [0, 0],
                    "nctrl_4": [0, 0],
                    "account_reset": [0, 0],
                    "sod_reset": [0, 0],
                    "nip_rule_v1_shadow": [0, 0],
                    "nip_rule_v2_shadow": [0, 0],
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
        side_effect=lambda **kwargs: None,
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

    period_status = response.results_by_period["ITD"].average_weight_methodology_status
    assert period_status is not None
    assert period_status.status == "NO_MATERIAL_SHADOW"
    assert period_status.is_material_shadow is False
    assert period_status.blocker_reason_codes == []
    assert response.audit.counts["average_weight_shadow_delta_positions"] == 0
    assert response.audit.counts["average_weight_shadow_delta_max_bp"] == 0
    assert response.audit.counts["average_weight_shadow_delta_sum_bp"] == 0
    assert response.audit.counts["average_weight_shadow_noise_periods"] == 0
    assert response.audit.counts["average_weight_shadow_warning_periods"] == 0
    assert response.audit.counts["average_weight_shadow_material_periods"] == 0
    assert response.audit.counts["average_weight_shadow_cutover_candidate_periods"] == 0
    assert response.audit.counts["average_weight_shadow_promotion_ready_rate_bp"] == 0
    assert response.audit.counts["average_weight_sum_residual_bp"] == 5000
    assert not any("Reset-aware average-weight shadow differs" in note for note in response.diagnostics.notes)
    assert any("average weights do not sum to 100% exactly" in note for note in response.diagnostics.notes)


def test_contribution_service_soft_flags_non_material_average_weight_shadow_delta(mocker):
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
                end_date=pd.Timestamp("2025-01-03").date(),
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
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "daily_ror": [1.0, 1.0, 1.0],
                    "perf_reset": [0, 1, 0],
                    "nip": [0, 0, 0],
                    "nctrl_4": [0, 0, 0],
                    "account_reset": [0, 0, 0],
                    "sod_reset": [0, 0, 0],
                    "nip_rule_v1_shadow": [0, 0, 0],
                    "nip_rule_v2_shadow": [0, 0, 0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
                "position_id": ["A", "A", "A"],
                "smoothed_contribution": [0.01, 0.01, 0.01],
                "smoothed_local_contribution": [0.01, 0.01, 0.01],
                "daily_weight": [0.5, 0.5, 0.4],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
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

    period_status = response.results_by_period["ITD"].average_weight_methodology_status
    assert period_status is not None
    assert period_status.status == "NO_MATERIAL_SHADOW"
    assert period_status.is_material_shadow is False
    assert period_status.blocker_reason_codes == []
    assert response.audit.counts["average_weight_shadow_delta_positions"] == 1
    assert response.audit.counts["average_weight_shadow_delta_max_bp"] == 167
    assert response.audit.counts["average_weight_shadow_delta_sum_bp"] == 167
    assert response.audit.counts["average_weight_shadow_noise_periods"] == 0
    assert response.audit.counts["average_weight_shadow_warning_periods"] == 1
    assert response.audit.counts["average_weight_shadow_material_periods"] == 0
    assert response.audit.counts["average_weight_shadow_cutover_candidate_periods"] == 0
    assert response.audit.counts["average_weight_shadow_promotion_ready_rate_bp"] == 0
    assert any("still under characterization" in note for note in response.diagnostics.notes)
    assert not any("differs materially" in note for note in response.diagnostics.notes)


def test_contribution_service_counts_clean_material_shadow_period_as_cutover_candidate(mocker):
    mocker.patch(
        "app.services.contribution_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE": "OFF",
            },
        )(),
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
                end_date=pd.Timestamp("2025-01-03").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame(
                {
                    "position_id": ["A", "A", "A", "B", "B", "B"],
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "perf_reset": [0, 1, 0, 0, 1, 0],
                    "bod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    "eod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                }
            ),
            pd.DataFrame(
                {
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "begin_mv": [1000.0, 1005.0, 1010.0],
                    "bod_cf": [0.0, 0.0, 0.0],
                    "daily_ror": [1.0, 1.0, 1.0],
                    "perf_reset": [0, 1, 0],
                    "nip": [0, 0, 0],
                    "nctrl_4": [0, 0, 0],
                    "account_reset": [0, 0, 0],
                    "sod_reset": [0, 0, 0],
                    "nip_rule_v1_shadow": [0, 0, 0],
                    "nip_rule_v2_shadow": [0, 0, 0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
                "position_id": ["A", "A", "A", "B", "B", "B"],
                "smoothed_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "smoothed_local_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "daily_weight": [0.10, 0.95, 0.95, 0.90, 0.05, 0.05],
                "perf_reset": [0, 1, 0, 0, 1, 0],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {"position_id": "A", "valuation_points": []},
                {"position_id": "B", "valuation_points": []},
            ],
            "emit": {"timeseries": True, "by_position_timeseries": True},
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    period_status = response.results_by_period["ITD"].average_weight_methodology_status
    assert period_status is not None
    assert period_status.status == "PROMOTION_READY"
    assert period_status.is_material_shadow is True
    assert period_status.is_cutover_candidate is True
    assert period_status.is_promoted is False
    assert period_status.blocker_reason_codes == []
    assert response.audit.counts["average_weight_shadow_material_periods"] == 1
    assert response.audit.counts["average_weight_shadow_cutover_candidate_periods"] == 1
    assert response.audit.counts["average_weight_shadow_promotion_ready_rate_bp"] == 10000
    assert response.audit.counts["average_weight_shadow_promoted_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_weight_residual_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_flow_balance_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_reset_alignment_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_timeseries_delta_periods"] == 0
    assert any(
        "strong candidates for a future denominator cutover study" in note for note in response.diagnostics.notes
    )
    assert any("rollout readiness is currently 10000 basis points" in note for note in response.diagnostics.notes)


def test_contribution_service_promotes_reset_aware_average_weight_for_candidate_periods_when_runtime_mode_enabled(
    mocker,
):
    mocker.patch(
        "app.services.contribution_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE": "CANDIDATE_PERIODS",
            },
        )(),
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
                end_date=pd.Timestamp("2025-01-03").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame(
                {
                    "position_id": ["A", "A", "A", "B", "B", "B"],
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "perf_reset": [0, 1, 0, 0, 1, 0],
                    "bod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    "eod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                }
            ),
            pd.DataFrame(
                {
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "begin_mv": [1000.0, 1005.0, 1010.0],
                    "bod_cf": [0.0, 0.0, 0.0],
                    "daily_ror": [1.0, 1.0, 1.0],
                    "perf_reset": [0, 1, 0],
                    "nip": [0, 0, 0],
                    "nctrl_4": [0, 0, 0],
                    "account_reset": [0, 0, 0],
                    "sod_reset": [0, 0, 0],
                    "nip_rule_v1_shadow": [0, 0, 0],
                    "nip_rule_v2_shadow": [0, 0, 0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
                "position_id": ["A", "A", "A", "B", "B", "B"],
                "smoothed_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "smoothed_local_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "daily_weight": [0.10, 0.95, 0.95, 0.90, 0.05, 0.05],
                "perf_reset": [0, 1, 0, 0, 1, 0],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {"position_id": "A", "valuation_points": []},
                {"position_id": "B", "valuation_points": []},
            ],
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    period_status = response.results_by_period["ITD"].average_weight_methodology_status
    assert period_status is not None
    assert period_status.status == "PROMOTED"
    assert period_status.is_material_shadow is True
    assert period_status.is_cutover_candidate is True
    assert period_status.is_promoted is True
    assert period_status.blocker_reason_codes == []
    assert response.audit.counts["average_weight_shadow_cutover_candidate_periods"] == 1
    assert response.audit.counts["average_weight_shadow_promotion_ready_rate_bp"] == 10000
    assert response.audit.counts["average_weight_shadow_promoted_periods"] == 1
    assert response.audit.counts["average_weight_shadow_blocked_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_weight_residual_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_flow_balance_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_reset_alignment_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_timeseries_delta_periods"] == 0
    position_contributions = response.results_by_period["ITD"].position_contributions
    assert position_contributions is not None
    position_contributions_by_id = {contribution.position_id: contribution for contribution in position_contributions}
    assert position_contributions_by_id["A"].average_weight == pytest.approx(95.0)
    assert position_contributions_by_id["B"].average_weight == pytest.approx(5.0)
    assert any("promotion was applied" in note for note in response.diagnostics.notes)
    assert any(
        "strong candidates for a future denominator cutover study" in note for note in response.diagnostics.notes
    )


def test_contribution_service_classifies_flow_balance_as_cutover_blocker_for_material_shadow_period(mocker):
    mocker.patch(
        "app.services.contribution_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE": "OFF",
            },
        )(),
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
                end_date=pd.Timestamp("2025-01-03").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame(
                {
                    "position_id": ["A", "A", "A", "B", "B", "B"],
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "perf_reset": [0, 1, 0, 0, 1, 0],
                    "bod_cf": [-50.0, 0.0, 0.0, 40.0, 0.0, 0.0],
                    "eod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                }
            ),
            pd.DataFrame(
                {
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "begin_mv": [1000.0, 1005.0, 1010.0],
                    "bod_cf": [0.0, 0.0, 0.0],
                    "daily_ror": [1.0, 1.0, 1.0],
                    "perf_reset": [0, 1, 0],
                    "nip": [0, 0, 0],
                    "nctrl_4": [0, 0, 0],
                    "account_reset": [0, 0, 0],
                    "sod_reset": [0, 0, 0],
                    "nip_rule_v1_shadow": [0, 0, 0],
                    "nip_rule_v2_shadow": [0, 0, 0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
                "position_id": ["A", "A", "A", "B", "B", "B"],
                "smoothed_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "smoothed_local_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "daily_weight": [0.10, 0.95, 0.95, 0.90, 0.05, 0.05],
                "perf_reset": [0, 1, 0, 0, 1, 0],
                "bod_cf": [-50.0, 0.0, 0.0, 40.0, 0.0, 0.0],
                "eod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {"position_id": "A", "valuation_points": []},
                {"position_id": "B", "valuation_points": []},
            ],
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    period_status = response.results_by_period["ITD"].average_weight_methodology_status
    assert period_status is not None
    assert period_status.status == "BLOCKED"
    assert period_status.is_material_shadow is True
    assert period_status.is_cutover_candidate is False
    assert period_status.is_promoted is False
    assert period_status.blocker_reason_codes == ["flow_balance"]
    assert response.audit.counts["average_weight_shadow_material_periods"] == 1
    assert response.audit.counts["average_weight_shadow_cutover_candidate_periods"] == 0
    assert response.audit.counts["average_weight_shadow_promotion_ready_rate_bp"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_periods"] == 1
    assert response.audit.counts["average_weight_shadow_blocked_by_weight_residual_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_flow_balance_periods"] == 1
    assert response.audit.counts["average_weight_shadow_blocked_by_reset_alignment_periods"] == 0
    assert response.audit.counts["average_weight_shadow_blocked_by_timeseries_delta_periods"] == 0
    assert any("stock and cash legs did not cancel cleanly" in note for note in response.diagnostics.notes)
    assert any(
        "remained shadow-only because one or more rollout guardrails were not yet clean" in note
        for note in response.diagnostics.notes
    )
    assert any("rollout readiness is currently 0 basis points" in note for note in response.diagnostics.notes)


def test_contribution_service_emits_grouped_return_alignment_note_when_position_and_portfolio_reset_days_differ(mocker):
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
                end_date=pd.Timestamp("2025-01-03").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame(
                {
                    "position_id": ["A", "A", "A"],
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "perf_reset": [0, 0, 1],
                }
            ),
            pd.DataFrame(
                {
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "daily_ror": [1.0, 1.0, 1.0],
                    "perf_reset": [0, 1, 0],
                    "nip": [0, 0, 0],
                    "nctrl_4": [0, 0, 0],
                    "account_reset": [0, 0, 0],
                    "sod_reset": [0, 0, 0],
                    "nip_rule_v1_shadow": [0, 0, 0],
                    "nip_rule_v2_shadow": [0, 0, 0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
                "position_id": ["A", "A", "A"],
                "smoothed_contribution": [0.01, 0.01, 0.01],
                "smoothed_local_contribution": [0.01, 0.01, 0.01],
                "daily_weight": [0.5, 0.5, 0.5],
                "perf_reset": [0, 0, 1],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
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

    assert response.audit.counts["portfolio_reset_days"] == 1
    assert response.audit.counts["position_reset_days"] == 1
    assert response.audit.counts["portfolio_reset_without_position_reset_days"] == 1
    assert response.audit.counts["position_reset_without_portfolio_reset_days"] == 1
    assert any("grouped-return alignment remains under characterization" in note for note in response.diagnostics.notes)


def test_contribution_service_classifies_reset_alignment_as_cutover_blocker_for_material_shadow_period(mocker):
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
                end_date=pd.Timestamp("2025-01-03").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame(
                {
                    "position_id": ["A", "A", "A", "B", "B", "B"],
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "perf_reset": [0, 0, 1, 0, 0, 1],
                    "bod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    "eod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                }
            ),
            pd.DataFrame(
                {
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "begin_mv": [1000.0, 1005.0, 1010.0],
                    "bod_cf": [0.0, 0.0, 0.0],
                    "daily_ror": [1.0, 1.0, 1.0],
                    "perf_reset": [0, 1, 0],
                    "nip": [0, 0, 0],
                    "nctrl_4": [0, 0, 0],
                    "account_reset": [0, 0, 0],
                    "sod_reset": [0, 0, 0],
                    "nip_rule_v1_shadow": [0, 0, 0],
                    "nip_rule_v2_shadow": [0, 0, 0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
                "position_id": ["A", "A", "A", "B", "B", "B"],
                "smoothed_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "smoothed_local_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "daily_weight": [0.10, 0.95, 0.95, 0.90, 0.05, 0.05],
                "perf_reset": [0, 0, 1, 0, 0, 1],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {"position_id": "A", "valuation_points": []},
                {"position_id": "B", "valuation_points": []},
            ],
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    period_status = response.results_by_period["ITD"].average_weight_methodology_status
    assert period_status is not None
    assert period_status.status == "BLOCKED"
    assert period_status.blocker_reason_codes == ["reset_alignment"]
    assert response.audit.counts["average_weight_shadow_blocked_periods"] == 1
    assert response.audit.counts["average_weight_shadow_blocked_by_reset_alignment_periods"] == 1
    assert response.audit.counts["average_weight_shadow_blocked_by_timeseries_delta_periods"] == 0
    assert any(
        "portfolio and position reset boundaries were not aligned" in note for note in response.diagnostics.notes
    )


def test_contribution_service_emits_carino_invalid_domain_note_for_broken_capital_path(mocker):
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
                    "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-02").date()],
                    "daily_ror": [-150.0, 10.0],
                    "perf_reset": [1, 0],
                    "nip": [0, 0],
                    "nctrl_4": [0, 1],
                    "account_reset": [0, 0],
                    "sod_reset": [0, 0],
                    "nip_rule_v1_shadow": [0, 0],
                    "nip_rule_v2_shadow": [0, 0],
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
                "smoothed_contribution": [-1.5, 0.1],
                "smoothed_local_contribution": [-1.5, 0.1],
                "daily_weight": [1.0, 1.0],
                "perf_reset": [1, 0],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "GROSS",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": -500},
                    {"perf_date": "2025-01-02", "begin_mv": -500, "bod_cf": 1000, "end_mv": 550},
                ],
            },
            "positions_data": [{"position_id": "A", "valuation_points": []}],
            "smoothing": {"method": "CARINO"},
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    assert response.audit.counts["carino_invalid_domain_days"] == 1
    assert any(
        "Carino smoothing fell back to raw daily contribution arithmetic" in note for note in response.diagnostics.notes
    )


def test_contribution_service_reconciles_daily_series_to_residual_adjusted_period_total(mocker):
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
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame({"position_id": ["A"]}),
            pd.DataFrame(
                {
                    "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-02").date()],
                    "daily_ror": [-150.0, 10.0],
                    "perf_reset": [1, 0],
                    "nip": [0, 0],
                    "nctrl_4": [0, 1],
                    "account_reset": [0, 0],
                    "sod_reset": [0, 0],
                    "nip_rule_v1_shadow": [0, 0],
                    "nip_rule_v2_shadow": [0, 0],
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
                "smoothed_contribution": [-0.5, 0.1],
                "smoothed_local_contribution": [-0.5, 0.1],
                "daily_weight": [1.0, 1.0],
                "perf_reset": [1, 0],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_reset_aware_period_portfolio_return",
        return_value=0.21578947,
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "GROSS",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": -500},
                    {"perf_date": "2025-01-02", "begin_mv": -500, "bod_cf": 1000, "end_mv": 550},
                ],
            },
            "positions_data": [{"position_id": "A", "valuation_points": []}],
            "emit": {"timeseries": True},
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    assert response.audit.counts["timeseries_total_delta_periods"] == 0
    assert not any("do not sum to the residual-adjusted period total" in note for note in response.diagnostics.notes)
    assert response.results_by_period["ITD"].timeseries is not None
    daily_total = sum(point.total_contribution for point in response.results_by_period["ITD"].timeseries)
    assert daily_total == pytest.approx(response.results_by_period["ITD"].total_contribution)


def test_contribution_service_surfaces_position_flow_balance_residuals(mocker):
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
                end_date=pd.Timestamp("2025-01-01").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame(
                {
                    "position_id": ["A", "B"],
                    "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-01").date()],
                    "bod_cf": [100.0, -90.0],
                    "eod_cf": [0.0, 0.0],
                }
            ),
            pd.DataFrame(
                {
                    "perf_date": [pd.Timestamp("2025-01-01").date()],
                    "begin_mv": [1000.0],
                    "bod_cf": [0.0],
                    "eod_cf": [0.0],
                    "daily_ror": [1.0],
                    "perf_reset": [0],
                    "nip": [0],
                    "nctrl_4": [0],
                    "account_reset": [0],
                    "sod_reset": [0],
                    "nip_rule_v1_shadow": [0],
                    "nip_rule_v2_shadow": [0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-01").date()],
                "position_id": ["A", "B"],
                "smoothed_contribution": [0.01, 0.02],
                "smoothed_local_contribution": [0.01, 0.02],
                "daily_weight": [0.6, 0.4],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {"position_id": "A", "valuation_points": []},
                {"position_id": "B", "valuation_points": []},
            ],
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    assert response.audit.counts["position_flow_residual_days"] == 1
    assert response.audit.counts["position_flow_residual_max_bp"] == 100
    assert response.audit.counts["position_flow_residual_sum_bp"] == 100
    assert any("materially non-flow-neutral scoped slice" in note for note in response.diagnostics.notes)
    assert any("maximum residual was 100 basis points" in note for note in response.diagnostics.notes)


def test_contribution_service_soft_flags_small_position_flow_residuals(mocker):
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
                end_date=pd.Timestamp("2025-01-01").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame(
                {
                    "position_id": ["A", "B"],
                    "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-01").date()],
                    "bod_cf": [100.0, -99.0],
                    "eod_cf": [0.0, 0.0],
                }
            ),
            pd.DataFrame(
                {
                    "perf_date": [pd.Timestamp("2025-01-01").date()],
                    "begin_mv": [1000.0],
                    "bod_cf": [0.0],
                    "eod_cf": [0.0],
                    "daily_ror": [1.0],
                    "perf_reset": [0],
                    "nip": [0],
                    "nctrl_4": [0],
                    "account_reset": [0],
                    "sod_reset": [0],
                    "nip_rule_v1_shadow": [0],
                    "nip_rule_v2_shadow": [0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-01").date()],
                "position_id": ["A", "B"],
                "smoothed_contribution": [0.01, 0.02],
                "smoothed_local_contribution": [0.01, 0.02],
                "daily_weight": [0.6, 0.4],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {"position_id": "A", "valuation_points": []},
                {"position_id": "B", "valuation_points": []},
            ],
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    assert response.audit.counts["position_flow_residual_days"] == 1
    assert response.audit.counts["position_flow_residual_max_bp"] == 10
    assert response.audit.counts["position_flow_residual_sum_bp"] == 10
    assert any("looks like a small non-flow-neutral scoped slice" in note for note in response.diagnostics.notes)
    assert not any("materially non-flow-neutral scoped slice" in note for note in response.diagnostics.notes)


def test_position_flow_balance_counts_reconcile_single_position_external_cash_story():
    instruments_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-17").date(),
                pd.Timestamp("2025-01-18").date(),
                pd.Timestamp("2025-01-19").date(),
            ],
            "bod_cf": [0.0, 5000.0, 0.0],
            "eod_cf": [0.0, 0.0, -2000.0],
        }
    )
    portfolio_results_df = pd.DataFrame(
        {
            "perf_date": [
                pd.Timestamp("2025-01-17").date(),
                pd.Timestamp("2025-01-18").date(),
                pd.Timestamp("2025-01-19").date(),
            ],
            "begin_mv": [10000.0, 10000.0, 15000.0],
            "bod_cf": [0.0, 5000.0, 0.0],
            "eod_cf": [0.0, 0.0, -2000.0],
        }
    )

    counts = contribution_service._calculate_position_flow_balance_counts(
        instruments_df,
        portfolio_results_df,
    )

    assert counts["position_flow_residual_days"] == 0
    assert counts["position_flow_residual_max_bp"] == 0
    assert counts["position_flow_residual_sum_bp"] == 0


def test_contribution_service_does_not_flag_external_cash_flows_as_position_residuals(mocker):
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
                name="EXPLICIT",
                start_date=pd.Timestamp("2025-01-17").date(),
                end_date=pd.Timestamp("2025-01-20").date(),
                value=PeriodType.EXPLICIT,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame(
                {
                    "position_id": ["CASH", "CASH", "CASH", "CASH"],
                    "perf_date": [
                        pd.Timestamp("2025-01-17").date(),
                        pd.Timestamp("2025-01-18").date(),
                        pd.Timestamp("2025-01-19").date(),
                        pd.Timestamp("2025-01-20").date(),
                    ],
                    "bod_cf": [0.0, 5000.0, 0.0, 0.0],
                    "eod_cf": [0.0, 0.0, -2000.0, 0.0],
                    "daily_weight": [1.0, 1.0, 1.0, 1.0],
                }
            ),
            pd.DataFrame(
                {
                    "perf_date": [
                        pd.Timestamp("2025-01-17").date(),
                        pd.Timestamp("2025-01-18").date(),
                        pd.Timestamp("2025-01-19").date(),
                        pd.Timestamp("2025-01-20").date(),
                    ],
                    "begin_mv": [10000.0, 10000.0, 15000.0, 13000.0],
                    "bod_cf": [0.0, 5000.0, 0.0, 0.0],
                    "eod_cf": [0.0, 0.0, -2000.0, 0.0],
                    "daily_ror": [0.0, 0.0, 0.0, 0.0],
                    "perf_reset": [0, 0, 0, 0],
                    "nip": [0, 0, 0, 0],
                    "nctrl_4": [0, 0, 0, 0],
                    "account_reset": [0, 0, 0, 0],
                    "sod_reset": [0, 0, 0, 0],
                    "nip_rule_v1_shadow": [0, 0, 0, 0],
                    "nip_rule_v2_shadow": [0, 0, 0, 0],
                    "final_cum_ror": [0.0, 0.0, 0.0, 0.0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-17").date(),
                    pd.Timestamp("2025-01-18").date(),
                    pd.Timestamp("2025-01-19").date(),
                    pd.Timestamp("2025-01-20").date(),
                ],
                "position_id": ["CASH", "CASH", "CASH", "CASH"],
                "smoothed_contribution": [0.0, 0.0, 0.0, 0.0],
                "smoothed_local_contribution": [0.0, 0.0, 0.0, 0.0],
                "daily_weight": [1.0, 1.0, 1.0, 1.0],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "CASH_ONLY",
            "report_start_date": "2025-01-17",
            "report_end_date": "2025-01-20",
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-17", "begin_mv": 10000, "end_mv": 10000},
                    {"perf_date": "2025-01-18", "begin_mv": 10000, "bod_cf": 5000, "end_mv": 15000},
                    {"perf_date": "2025-01-19", "begin_mv": 15000, "eod_cf": -2000, "end_mv": 13000},
                    {"perf_date": "2025-01-20", "begin_mv": 13000, "end_mv": 13000},
                ],
            },
            "positions_data": [{"position_id": "CASH", "valuation_points": []}],
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    assert response.audit.counts["position_flow_residual_days"] == 0
    assert response.audit.counts["position_flow_residual_max_bp"] == 0
    assert response.audit.counts["position_flow_residual_sum_bp"] == 0
    assert not any("non-flow-neutral scoped slice" in note for note in response.diagnostics.notes)


def test_contribution_service_classifies_timeseries_reconciliation_as_cutover_blocker(mocker):
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
                end_date=pd.Timestamp("2025-01-03").date(),
                value=PeriodType.ITD,
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service._prepare_hierarchical_data",
        return_value=(
            pd.DataFrame(
                {
                    "position_id": ["A", "A", "A", "B", "B", "B"],
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "perf_reset": [0, 1, 0, 0, 1, 0],
                    "bod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    "eod_cf": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                }
            ),
            pd.DataFrame(
                {
                    "perf_date": [
                        pd.Timestamp("2025-01-01").date(),
                        pd.Timestamp("2025-01-02").date(),
                        pd.Timestamp("2025-01-03").date(),
                    ],
                    "begin_mv": [1000.0, 1005.0, 1010.0],
                    "bod_cf": [0.0, 0.0, 0.0],
                    "daily_ror": [1.0, 1.0, 1.0],
                    "perf_reset": [0, 1, 0],
                    "nip": [0, 0, 0],
                    "nctrl_4": [0, 0, 0],
                    "account_reset": [0, 0, 0],
                    "sod_reset": [0, 0, 0],
                    "nip_rule_v1_shadow": [0, 0, 0],
                    "nip_rule_v2_shadow": [0, 0, 0],
                }
            ),
        ),
    )
    mocker.patch(
        "app.services.contribution_service._calculate_daily_instrument_contributions",
        return_value=pd.DataFrame(
            {
                "perf_date": [
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                    pd.Timestamp("2025-01-01").date(),
                    pd.Timestamp("2025-01-02").date(),
                    pd.Timestamp("2025-01-03").date(),
                ],
                "position_id": ["A", "A", "A", "B", "B", "B"],
                "smoothed_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "smoothed_local_contribution": [0.01, 0.01, 0.01, 0.02, 0.02, 0.02],
                "daily_weight": [0.10, 0.95, 0.95, 0.90, 0.05, 0.05],
                "perf_reset": [0, 1, 0, 0, 1, 0],
            }
        ),
    )
    mocker.patch(
        "app.services.contribution_service._build_residual_adjusted_position_timeseries",
        return_value=[
            PositionContributionSeries(
                position_id="A",
                series=[
                    PositionDailyContribution(date=pd.Timestamp("2025-01-01").date(), contribution=100.0),
                ],
            )
        ],
    )
    mocker.patch(
        "app.services.contribution_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    request = ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                    {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020},
                    {"perf_date": "2025-01-03", "begin_mv": 1020, "end_mv": 1030},
                ],
            },
            "positions_data": [
                {"position_id": "A", "valuation_points": []},
                {"position_id": "B", "valuation_points": []},
            ],
            "emit": {"timeseries": True},
        }
    )

    response = contribution_service.calculate_contribution(
        request,
        input_fingerprint="fingerprint",
        calculation_hash="hash",
    )

    period_status = response.results_by_period["ITD"].average_weight_methodology_status
    assert period_status is not None
    assert period_status.status == "BLOCKED"
    assert period_status.blocker_reason_codes == ["timeseries_reconciliation"]
    assert response.audit.counts["timeseries_total_delta_periods"] == 1
    assert response.audit.counts["average_weight_shadow_blocked_periods"] == 1
    assert response.audit.counts["average_weight_shadow_blocked_by_timeseries_delta_periods"] == 1
    assert any(
        "daily contribution series still drifted from the residual-adjusted period total" in note
        for note in response.diagnostics.notes
    )
    assert any("do not sum to the residual-adjusted period total" in note for note in response.diagnostics.notes)


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
                                "portfolio_weight_avg": 100.0,
                                "benchmark_weight_avg": 100.0,
                                "portfolio_return": 1.5,
                                "benchmark_return": 1.0,
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
