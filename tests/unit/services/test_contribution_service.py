from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from app.models.contribution_analytics_requests import ContributionInputMode
from app.models.contribution_responses import (
    AverageWeightMethodologyStatus,
    PositionContribution,
    SinglePeriodContributionResult,
)
from app.services import contribution_service
from app.services.contribution_audit import AverageWeightShadowAuditState
from app.services.contribution_periods import ContributionPeriodMethodologyContext
from engine.schema import PortfolioColumns


def test_build_contribution_period_result_projects_flat_and_hierarchy_outputs():
    methodology_status = AverageWeightMethodologyStatus(
        status="PROMOTED",
        max_shadow_delta_bp=25,
        is_material_shadow=False,
        is_cutover_candidate=True,
        is_promoted=True,
    )
    supportability = contribution_service._ContributionPeriodSupportability(
        average_weight_sum_residual_bp=7,
        total_contribution=3.25,
        smoothing_evidence=None,
        average_weight_methodology_status=methodology_status,
    )
    position_contributions = [
        PositionContribution(
            position_id="SEC_A",
            total_contribution=3.25,
            average_weight=100.0,
            total_return=3.25,
        )
    ]

    flat_result = contribution_service._build_contribution_period_result(
        period_name="ITD",
        total_portfolio_return=0.0325,
        supportability=supportability,
        position_contributions=position_contributions,
        daily_series=None,
        emitted_position_series=None,
    )
    hierarchy_result = contribution_service._build_contribution_period_result(
        period_name="ITD",
        total_portfolio_return=0.0325,
        supportability=supportability,
        position_contributions=position_contributions,
        daily_series=None,
        emitted_position_series=None,
        hierarchy_results={
            "summary": {
                "portfolio_contribution": 3.25,
                "coverage_mv_pct": 100.0,
                "weighting_scheme": "average_weight",
            },
            "levels": [
                {
                    "level": 1,
                    "name": "sector",
                    "rows": [{"key": {"sector": "Technology"}, "contribution": 3.25}],
                }
            ],
        },
    )

    assert flat_result.period_name == "ITD"
    assert flat_result.average_weight_sum_residual_bp == 7
    assert flat_result.result.total_portfolio_return == pytest.approx(3.25)
    assert flat_result.result.total_contribution == pytest.approx(3.25)
    assert flat_result.result.position_contributions == position_contributions
    assert flat_result.result.average_weight_methodology_status == methodology_status
    assert flat_result.result.summary is None
    assert flat_result.result.levels is None
    assert hierarchy_result.result.summary is not None
    assert hierarchy_result.result.summary.portfolio_contribution == pytest.approx(3.25)
    assert hierarchy_result.result.levels is not None
    assert hierarchy_result.result.levels[0].rows[0].key == {"sector": "Technology"}


def test_prepare_contribution_engine_inputs_resolves_master_window_and_normalizes_dates(monkeypatch):
    periods = [
        SimpleNamespace(name="JAN", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)),
        SimpleNamespace(name="FEB", start_date=date(2026, 2, 1), end_date=date(2026, 2, 28)),
    ]
    instruments_df = pd.DataFrame({"instrument_id": ["A"]})
    portfolio_results_df = pd.DataFrame({"portfolio_id": ["P"]})
    daily_contributions_df = pd.DataFrame({PortfolioColumns.PERF_DATE.value: ["2026-01-02"]})
    request = SimpleNamespace(
        analyses=[SimpleNamespace(period="JAN"), SimpleNamespace(period="FEB")],
        portfolio_data=SimpleNamespace(valuation_points=[SimpleNamespace(perf_date=date(2025, 12, 31))]),
        report_end_date=date(2026, 2, 28),
        report_start_date=date(2026, 1, 1),
        weighting_scheme="daily",
        smoothing=SimpleNamespace(method="NONE"),
    )
    resolve_calls: list[tuple[object, ...]] = []

    def resolve_periods(periods_to_resolve, report_end_date, inception_date, *, explicit_start_date):
        resolve_calls.append((periods_to_resolve, report_end_date, inception_date, explicit_start_date))
        return periods

    monkeypatch.setattr(contribution_service, "resolve_periods", resolve_periods)
    monkeypatch.setattr(
        contribution_service,
        "_prepare_hierarchical_data",
        lambda prepared_request: (instruments_df, portfolio_results_df),
    )
    monkeypatch.setattr(
        contribution_service,
        "_calculate_daily_instrument_contributions",
        lambda *_args: daily_contributions_df,
    )

    result = contribution_service._prepare_contribution_engine_inputs(request)

    assert resolve_calls == [(["JAN", "FEB"], date(2026, 2, 28), date(2025, 12, 31), date(2026, 1, 1))]
    assert result.periods_to_resolve == ["JAN", "FEB"]
    assert result.resolved_periods == periods
    assert result.master_start_date == date(2026, 1, 1)
    assert result.master_end_date == date(2026, 2, 28)
    assert result.instruments_df is instruments_df
    assert result.portfolio_results_df is portfolio_results_df
    assert result.daily_contributions_df[PortfolioColumns.PERF_DATE.value].tolist() == [date(2026, 1, 2)]


def test_prepare_contribution_engine_inputs_rejects_unresolved_periods(monkeypatch):
    request = SimpleNamespace(
        analyses=[SimpleNamespace(period="MTD")],
        portfolio_data=SimpleNamespace(valuation_points=[]),
        report_end_date=date(2026, 2, 28),
        report_start_date=None,
    )
    monkeypatch.setattr(contribution_service, "resolve_periods", lambda *_args, **_kwargs: [])

    try:
        contribution_service._prepare_contribution_engine_inputs(request)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "No valid periods could be resolved."
    else:
        raise AssertionError("Expected HTTPException for unresolved contribution periods.")


def test_resolve_contribution_periods_uses_report_end_as_inception_without_valuations(monkeypatch):
    period = SimpleNamespace(name="MTD", start_date=date(2026, 2, 1), end_date=date(2026, 2, 28))
    request = SimpleNamespace(
        analyses=[SimpleNamespace(period="MTD")],
        portfolio_data=SimpleNamespace(valuation_points=[]),
        report_end_date=date(2026, 2, 28),
        report_start_date=None,
    )
    resolve_calls: list[tuple[object, ...]] = []

    def resolve_periods(periods_to_resolve, report_end_date, inception_date, *, explicit_start_date):
        resolve_calls.append((periods_to_resolve, report_end_date, inception_date, explicit_start_date))
        return [period]

    monkeypatch.setattr(contribution_service, "resolve_periods", resolve_periods)

    result = contribution_service._resolve_contribution_periods(request)

    assert resolve_calls == [(["MTD"], date(2026, 2, 28), date(2026, 2, 28), None)]
    assert result.resolved_periods == [period]
    assert result.master_start_date == date(2026, 2, 1)
    assert result.master_end_date == date(2026, 2, 28)


def test_build_contribution_results_by_period_routes_flat_periods_and_tracks_max_residual(monkeypatch):
    periods = [
        SimpleNamespace(name="JAN"),
        SimpleNamespace(name="FEB"),
        SimpleNamespace(name="MAR"),
    ]
    request = SimpleNamespace(hierarchy=[])
    audit_state = AverageWeightShadowAuditState()
    result_jan = SinglePeriodContributionResult(total_portfolio_return=1.0, total_contribution=1.0)
    result_mar = SinglePeriodContributionResult(total_portfolio_return=3.0, total_contribution=3.0)
    flat_calls: list[str] = []

    def build_flat_period_result(**kwargs):
        flat_calls.append(kwargs["period"].name)
        if kwargs["period"].name == "FEB":
            return None
        return contribution_service._ContributionPeriodResult(
            period_name=kwargs["period"].name,
            result=result_jan if kwargs["period"].name == "JAN" else result_mar,
            average_weight_sum_residual_bp=7 if kwargs["period"].name == "JAN" else 3,
        )

    monkeypatch.setattr(contribution_service, "_build_flat_period_contribution_result", build_flat_period_result)

    result = contribution_service._build_contribution_results_by_period(
        request=request,
        resolved_periods=periods,
        daily_contributions_df=pd.DataFrame(),
        portfolio_results_df=pd.DataFrame(),
        reset_aware_average_weight_mode="candidate_periods",
        average_weight_audit_state=audit_state,
    )

    assert flat_calls == ["JAN", "FEB", "MAR"]
    assert list(result.results_by_period) == ["JAN", "MAR"]
    assert result.results_by_period["JAN"] is result_jan
    assert result.results_by_period["MAR"] is result_mar
    assert result.average_weight_sum_residual_bp == 7


def test_build_contribution_results_by_period_routes_hierarchy_periods(monkeypatch):
    periods = [SimpleNamespace(name="QTD")]
    request = SimpleNamespace(hierarchy=["sector"])
    audit_state = AverageWeightShadowAuditState()
    period_result = SinglePeriodContributionResult(total_portfolio_return=2.0, total_contribution=2.0)
    hierarchy_calls: list[str] = []

    def build_hierarchy_period_result(**kwargs):
        hierarchy_calls.append(kwargs["period"].name)
        return contribution_service._ContributionPeriodResult(
            period_name="QTD",
            result=period_result,
            average_weight_sum_residual_bp=11,
        )

    monkeypatch.setattr(
        contribution_service,
        "_build_hierarchy_period_contribution_result",
        build_hierarchy_period_result,
    )

    result = contribution_service._build_contribution_results_by_period(
        request=request,
        resolved_periods=periods,
        daily_contributions_df=pd.DataFrame(),
        portfolio_results_df=pd.DataFrame(),
        reset_aware_average_weight_mode="off",
        average_weight_audit_state=audit_state,
    )

    assert hierarchy_calls == ["QTD"]
    assert result.results_by_period == {"QTD": period_result}
    assert result.average_weight_sum_residual_bp == 11


def test_run_contribution_calculation_prepares_engine_inputs_and_period_results(monkeypatch):
    request = SimpleNamespace(calculation_id="contribution-calc-1")
    periods = [SimpleNamespace(name="ITD")]
    portfolio_results_df = pd.DataFrame({"portfolio_id": ["P-1"]})
    daily_contributions_df = pd.DataFrame({PortfolioColumns.PERF_DATE.value: [date(2026, 1, 31)]})
    engine_inputs = contribution_service._ContributionEngineInputs(
        periods_to_resolve=["ITD"],
        resolved_periods=periods,
        master_start_date=date(2026, 1, 1),
        master_end_date=date(2026, 1, 31),
        instruments_df=pd.DataFrame({"instrument_id": ["A"]}),
        portfolio_results_df=portfolio_results_df,
        daily_contributions_df=daily_contributions_df,
    )
    period_result = SinglePeriodContributionResult(total_portfolio_return=0.02, total_contribution=0.02)
    period_calls: list[dict[str, object]] = []

    def build_period_results(**kwargs):
        period_calls.append(kwargs)
        return contribution_service._ContributionPeriodResults(
            results_by_period={"ITD": period_result},
            average_weight_sum_residual_bp=9,
        )

    monkeypatch.setattr(contribution_service, "_prepare_contribution_engine_inputs", lambda _request: engine_inputs)
    monkeypatch.setattr(contribution_service, "_build_contribution_results_by_period", build_period_results)

    result = contribution_service._run_contribution_calculation(
        request,
        reset_aware_average_weight_mode="candidate_periods",
    )

    assert result.engine_inputs is engine_inputs
    assert result.results_by_period == {"ITD": period_result}
    assert isinstance(result.average_weight_audit_state, AverageWeightShadowAuditState)
    assert result.average_weight_sum_residual_bp == 9
    assert period_calls == [
        {
            "request": request,
            "resolved_periods": periods,
            "daily_contributions_df": daily_contributions_df,
            "portfolio_results_df": portfolio_results_df,
            "reset_aware_average_weight_mode": "candidate_periods",
            "average_weight_audit_state": result.average_weight_audit_state,
        }
    ]


def test_run_contribution_calculation_records_http_failure(monkeypatch):
    request = SimpleNamespace(calculation_id="contribution-calc-1")
    failures: list[dict[str, object]] = []
    source_error = HTTPException(status_code=400, detail="No valid periods could be resolved.")

    def prepare_engine_inputs(_request):
        raise source_error

    monkeypatch.setattr(contribution_service, "_prepare_contribution_engine_inputs", prepare_engine_inputs)
    monkeypatch.setattr(contribution_service, "record_execution_failure", lambda **kwargs: failures.append(kwargs))

    with pytest.raises(HTTPException) as exc_info:
        contribution_service._run_contribution_calculation(
            request,
            reset_aware_average_weight_mode="off",
        )

    assert exc_info.value is source_error
    assert failures == [
        {
            "calculation_id": "contribution-calc-1",
            "message": "No valid periods could be resolved.",
            "execution_stage_started": True,
        }
    ]


def test_run_contribution_calculation_maps_unexpected_failure(monkeypatch):
    request = SimpleNamespace(calculation_id="contribution-calc-1")
    failures: list[dict[str, object]] = []

    def prepare_engine_inputs(_request):
        raise RuntimeError("engine unavailable")

    monkeypatch.setattr(contribution_service, "_prepare_contribution_engine_inputs", prepare_engine_inputs)
    monkeypatch.setattr(contribution_service, "record_execution_failure", lambda **kwargs: failures.append(kwargs))

    with pytest.raises(HTTPException) as exc_info:
        contribution_service._run_contribution_calculation(
            request,
            reset_aware_average_weight_mode="off",
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "An unexpected error occurred during contribution calculation: engine unavailable"
    assert failures == [
        {
            "calculation_id": "contribution-calc-1",
            "message": "An unexpected error occurred during contribution calculation: engine unavailable",
            "execution_stage_started": True,
        }
    ]


def test_build_contribution_response_evidence_preserves_audit_supportability_and_source_inputs(monkeypatch):
    request = SimpleNamespace(
        calculation_id="contribution-calc-1",
        positions_data=["A", "B"],
        report_end_date=date(2026, 3, 31),
        smoothing=SimpleNamespace(method="CARINO"),
    )
    diagnostics = SimpleNamespace(notes=[])
    supportability = SimpleNamespace(status="READY")
    source_economics = SimpleNamespace(mode="source-economics")
    audit_state = AverageWeightShadowAuditState()
    diagnostic_calls: list[dict[str, object]] = []
    supportability_calls: list[dict[str, object]] = []
    source_calls: list[dict[str, object]] = []
    metric_calls: list[dict[str, object]] = []

    def append_diagnostic_notes(diagnostics_model, **kwargs):
        diagnostic_calls.append({"diagnostics": diagnostics_model, **kwargs})

    audit_state.append_diagnostic_notes = append_diagnostic_notes  # type: ignore[method-assign]
    monkeypatch.setattr(contribution_service, "_build_portfolio_engine_diagnostics", lambda *_args: diagnostics)
    monkeypatch.setattr(contribution_service, "_count_carino_invalid_domain_days", lambda _df: 4)
    monkeypatch.setattr(
        contribution_service,
        "_calculate_grouped_return_reset_alignment_counts",
        lambda *_args: {"grouped_return_reset_alignment_drift_days": 2},
    )
    monkeypatch.setattr(
        contribution_service,
        "_calculate_position_flow_balance_counts",
        lambda *_args: {"position_flow_residual_days": 1},
    )
    monkeypatch.setattr(contribution_service, "_count_contribution_input_rows", lambda _request: 9)
    monkeypatch.setattr(
        contribution_service,
        "_latest_contribution_observation_date",
        lambda _request: date(2026, 3, 30),
    )
    monkeypatch.setattr(
        contribution_service,
        "_list_upstream_snapshots_for_contribution",
        lambda calculation_id: [f"snapshot-for-{calculation_id}"],
    )

    def build_calculation_supportability(**kwargs):
        supportability_calls.append(kwargs)
        return supportability

    def build_source_economics(**kwargs):
        source_calls.append(kwargs)
        return source_economics

    def record_metric(**kwargs):
        metric_calls.append(kwargs)

    monkeypatch.setattr(contribution_service, "build_calculation_supportability", build_calculation_supportability)
    monkeypatch.setattr(contribution_service, "build_contribution_source_economics_evidence", build_source_economics)
    monkeypatch.setattr(contribution_service, "record_supportability_metric", record_metric)

    evidence = contribution_service._build_contribution_response_evidence(
        request=request,
        input_mode=ContributionInputMode.STATELESS,
        instruments_df=pd.DataFrame(),
        portfolio_results_df=pd.DataFrame(),
        master_start_date=date(2026, 1, 1),
        resolved_period_count=3,
        average_weight_audit_state=audit_state,
        average_weight_sum_residual_bp=17,
    )

    assert evidence.diagnostics is diagnostics
    assert evidence.audit.counts["input_positions"] == 2
    assert evidence.audit.counts["average_weight_sum_residual_bp"] == 17
    assert evidence.audit.counts["carino_invalid_domain_days"] == 4
    assert evidence.audit.counts["grouped_return_reset_alignment_drift_days"] == 2
    assert evidence.audit.counts["position_flow_residual_days"] == 1
    assert evidence.calculation_supportability is supportability
    assert evidence.source_economics_evidence is source_economics
    assert diagnostic_calls == [
        {
            "diagnostics": diagnostics,
            "average_weight_sum_residual_bp": 17,
            "carino_invalid_domain_days": 4,
            "reset_alignment_counts": {"grouped_return_reset_alignment_drift_days": 2},
            "position_flow_balance_counts": {"position_flow_residual_days": 1},
        }
    ]
    assert supportability_calls == [
        {
            "input_row_count": 9,
            "resolved_period_count": 3,
            "latest_observation_date": date(2026, 3, 30),
            "report_end_date": date(2026, 3, 31),
        }
    ]
    assert source_calls == [
        {
            "request": request,
            "input_mode": ContributionInputMode.STATELESS,
            "upstream_snapshots": ["snapshot-for-contribution-calc-1"],
        }
    ]
    assert metric_calls == [{"operation": "contribution", "supportability": supportability}]


def test_complete_contribution_execution_preserves_lineage_handoff(monkeypatch):
    request = SimpleNamespace(calculation_id="contribution-calc-1", positions_data=["A", "B", "C"])
    response_model = SimpleNamespace(calculation_id="contribution-calc-1")
    portfolio_results_df = pd.DataFrame({"portfolio_id": ["P"]})
    daily_contributions_df = pd.DataFrame({"position_id": ["A"]})
    completion_calls: list[dict[str, object]] = []

    def complete_execution_with_lineage(**kwargs):
        completion_calls.append(kwargs)

    monkeypatch.setattr(contribution_service, "complete_execution_with_lineage", complete_execution_with_lineage)

    contribution_service._complete_contribution_execution(
        request=request,
        response_model=response_model,
        portfolio_results_df=portfolio_results_df,
        daily_contributions_df=daily_contributions_df,
    )

    assert len(completion_calls) == 1
    completion = completion_calls[0]
    assert completion["calculation_id"] == "contribution-calc-1"
    assert completion["calculation_type"] == "Contribution"
    assert completion["request_model"] is request
    assert completion["response_model"] is response_model
    assert completion["execution_details"] == {"input_positions": 3}
    calculation_details = completion["calculation_details"]
    assert calculation_details["portfolio_twr.csv"] is portfolio_results_df
    assert calculation_details["daily_contributions.csv"] is daily_contributions_df


def test_record_average_weight_shadow_observation_projects_methodology_deltas():
    audit_state = AverageWeightShadowAuditState()
    methodology_context = ContributionPeriodMethodologyContext(
        average_weight_shadow_df=pd.DataFrame(),
        delta_positions=3,
        max_shadow_delta_bp=125,
        sum_shadow_delta_bp=175,
        position_reset_dates=set(),
        portfolio_reset_dates=set(),
        position_flow_balance_counts={"position_flow_residual_days": 0},
    )

    contribution_service._record_average_weight_shadow_observation(
        average_weight_audit_state=audit_state,
        period_methodology_context=methodology_context,
    )

    assert audit_state.delta_positions == 3
    assert audit_state.delta_max_bp == 125
    assert audit_state.delta_sum_bp == 175


def test_prepare_contribution_period_projects_frames_methodology_and_audit(monkeypatch):
    period_slice_df = pd.DataFrame({"position_id": ["A"], "smoothed_contribution": [0.01]})
    portfolio_period_slice_df = pd.DataFrame({"portfolio_id": ["P"]})
    methodology_context = ContributionPeriodMethodologyContext(
        average_weight_shadow_df=pd.DataFrame({"position_id": ["A"], "average_weight": [0.5]}),
        delta_positions=2,
        max_shadow_delta_bp=50,
        sum_shadow_delta_bp=75,
        position_reset_dates=set(),
        portfolio_reset_dates=set(),
        position_flow_balance_counts={"position_flow_residual_days": 0},
    )
    period = SimpleNamespace(name="QTD", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31))
    audit_state = AverageWeightShadowAuditState()
    daily_contributions_df = pd.DataFrame()
    portfolio_results_df = pd.DataFrame()
    slice_calls: list[dict[str, object]] = []
    context_calls: list[dict[str, object]] = []

    def slice_period_frames(**kwargs):
        slice_calls.append(kwargs)
        return SimpleNamespace(
            period_slice_df=period_slice_df,
            portfolio_period_slice_df=portfolio_period_slice_df,
        )

    def build_methodology_context(**kwargs):
        context_calls.append(kwargs)
        return methodology_context

    monkeypatch.setattr(contribution_service, "_slice_contribution_period_frames", slice_period_frames)
    monkeypatch.setattr(
        contribution_service,
        "_build_contribution_period_methodology_context",
        build_methodology_context,
    )

    preparation = contribution_service._prepare_contribution_period(
        daily_contributions_df=daily_contributions_df,
        portfolio_results_df=portfolio_results_df,
        period=period,
        average_weight_audit_state=audit_state,
    )

    assert preparation is not None
    assert preparation.period_slice_df is period_slice_df
    assert preparation.portfolio_period_slice_df is portfolio_period_slice_df
    assert preparation.period_methodology_context is methodology_context
    assert audit_state.delta_positions == 2
    assert audit_state.delta_max_bp == 50
    assert audit_state.delta_sum_bp == 75
    assert len(slice_calls) == 1
    assert slice_calls[0]["daily_contributions_df"] is daily_contributions_df
    assert slice_calls[0]["portfolio_results_df"] is portfolio_results_df
    assert slice_calls[0]["start_date"] == date(2026, 1, 1)
    assert slice_calls[0]["end_date"] == date(2026, 3, 31)
    assert context_calls == [
        {
            "period_slice_df": period_slice_df,
            "portfolio_period_slice_df": portfolio_period_slice_df,
        }
    ]


def test_prepare_contribution_period_requires_portfolio_slice_when_requested(monkeypatch):
    period_slice_df = pd.DataFrame({"position_id": ["A"], "smoothed_contribution": [0.01]})
    period = SimpleNamespace(name="ITD", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31))
    audit_state = AverageWeightShadowAuditState()

    monkeypatch.setattr(
        contribution_service,
        "_slice_contribution_period_frames",
        lambda **_kwargs: SimpleNamespace(
            period_slice_df=period_slice_df,
            portfolio_period_slice_df=pd.DataFrame(),
        ),
    )
    monkeypatch.setattr(
        contribution_service,
        "_build_contribution_period_methodology_context",
        lambda **_kwargs: pytest.fail("empty hierarchy portfolio slice should stop before methodology context"),
    )

    preparation = contribution_service._prepare_contribution_period(
        daily_contributions_df=pd.DataFrame(),
        portfolio_results_df=pd.DataFrame(),
        period=period,
        average_weight_audit_state=audit_state,
        require_portfolio_slice=True,
    )

    assert preparation is None
    assert audit_state.delta_positions == 0


def test_build_contribution_period_supportability_preserves_evidence_inputs(monkeypatch):
    period_slice_df = pd.DataFrame({"position_id": ["A"], "smoothed_contribution": [0.01]})
    portfolio_period_slice_df = pd.DataFrame({"portfolio_id": ["P"]})
    methodology_context = ContributionPeriodMethodologyContext(
        average_weight_shadow_df=pd.DataFrame({"position_id": ["A"], "average_weight": [0.5]}),
        delta_positions=1,
        max_shadow_delta_bp=25,
        sum_shadow_delta_bp=40,
        position_reset_dates=set(),
        portfolio_reset_dates=set(),
        position_flow_balance_counts={"position_flow_residual_days": 0},
    )
    position_contributions = [
        PositionContribution(
            position_id="A",
            total_contribution=2.5,
            average_weight=50.0,
            total_return=5.0,
        ),
        PositionContribution(
            position_id="B",
            total_contribution=1.5,
            average_weight=50.0,
            total_return=3.0,
        ),
    ]
    audit_state = AverageWeightShadowAuditState()
    smoothing_calls: list[dict[str, object]] = []
    methodology_calls: list[dict[str, object]] = []

    monkeypatch.setattr(contribution_service, "_calculate_average_weight_sum_residual_bp", lambda _rows: 17)

    def build_smoothing_evidence(**kwargs):
        smoothing_calls.append(kwargs)
        return SimpleNamespace(status="OK")

    def build_methodology_status(**kwargs):
        methodology_calls.append(kwargs)
        return AverageWeightMethodologyStatus(
            status="PROMOTED",
            max_shadow_delta_bp=25,
            is_material_shadow=False,
            is_cutover_candidate=True,
            is_promoted=True,
        )

    monkeypatch.setattr(contribution_service, "_build_contribution_smoothing_evidence", build_smoothing_evidence)
    monkeypatch.setattr(contribution_service, "_record_period_timeseries_total_delta", lambda **_kwargs: 3)
    monkeypatch.setattr(
        contribution_service, "_build_period_average_weight_methodology_status", build_methodology_status
    )

    result = contribution_service._build_contribution_period_supportability(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=portfolio_period_slice_df,
        position_contributions=position_contributions,
        daily_series=None,
        total_portfolio_return=0.04,
        smoothing_method="CARINO",
        residual_allocation_applied=True,
        residual_allocation_basis="reset_aware_average_weight_shadow",
        period_methodology_context=methodology_context,
        average_weight_audit_state=audit_state,
        is_promoted=True,
    )

    assert result.average_weight_sum_residual_bp == 17
    assert result.total_contribution == pytest.approx(4.0)
    assert result.smoothing_evidence.status == "OK"
    assert result.average_weight_methodology_status.is_promoted is True
    assert smoothing_calls[0]["linked_return"] == 0.04
    assert smoothing_calls[0]["final_contribution"] == pytest.approx(0.04)
    assert smoothing_calls[0]["residual_allocation_applied"] is True
    assert smoothing_calls[0]["residual_allocation_basis"] == "reset_aware_average_weight_shadow"
    assert methodology_calls[0]["period_methodology_context"] is methodology_context
    assert methodology_calls[0]["average_weight_sum_residual_bp"] == 17
    assert methodology_calls[0]["timeseries_total_delta_periods"] == 3
    assert methodology_calls[0]["average_weight_audit_state"] is audit_state
    assert methodology_calls[0]["is_promoted"] is True


def test_build_flat_period_contribution_result_preserves_average_weight_basis(monkeypatch):
    period_slice_df = pd.DataFrame({"position_id": ["A"], "smoothed_contribution": [0.01]})
    portfolio_period_slice_df = pd.DataFrame({"portfolio_id": ["P"]})
    totals_df = pd.DataFrame({"position_id": ["A"], "selected_average_weight": [0.5]})
    average_weight_shadow_df = pd.DataFrame(
        {
            "position_id": ["A"],
            "average_weight": [0.4],
            "reset_aware_average_weight_shadow": [0.5],
        }
    )
    period = SimpleNamespace(name="QTD", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31))
    request = SimpleNamespace(
        smoothing=SimpleNamespace(method="CARINO"),
        emit=SimpleNamespace(timeseries=False, by_position_timeseries=False),
    )
    audit_state = AverageWeightShadowAuditState()
    residual_calls: list[dict[str, object]] = []
    smoothing_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        contribution_service,
        "_slice_contribution_period_frames",
        lambda **_kwargs: SimpleNamespace(
            period_slice_df=period_slice_df,
            portfolio_period_slice_df=portfolio_period_slice_df,
        ),
    )
    monkeypatch.setattr(
        contribution_service,
        "_build_contribution_period_methodology_context",
        lambda **_kwargs: SimpleNamespace(
            delta_positions=2,
            max_shadow_delta_bp=125,
            sum_shadow_delta_bp=175,
            average_weight_shadow_df=average_weight_shadow_df,
        ),
    )
    monkeypatch.setattr(
        contribution_service,
        "_select_period_average_weight_column",
        lambda **_kwargs: ("reset_aware_average_weight_shadow", True),
    )
    monkeypatch.setattr(
        contribution_service,
        "_calculate_reset_aware_period_portfolio_return",
        lambda *_args: 0.0348,
    )

    def build_residual_adjusted_position_totals(**kwargs):
        residual_calls.append(kwargs)
        return SimpleNamespace(totals_df=totals_df, residual_allocation_applied=True)

    monkeypatch.setattr(
        contribution_service,
        "build_residual_adjusted_position_totals",
        build_residual_adjusted_position_totals,
    )
    monkeypatch.setattr(
        contribution_service,
        "build_position_contributions",
        lambda **_kwargs: [
            PositionContribution(
                position_id="A",
                total_contribution=3.48,
                average_weight=50.0,
                total_return=6.96,
            )
        ],
    )
    monkeypatch.setattr(
        contribution_service,
        "_build_period_contribution_series_outputs",
        lambda **_kwargs: ([], None, None),
    )
    monkeypatch.setattr(contribution_service, "_calculate_average_weight_sum_residual_bp", lambda _rows: 12)

    def build_smoothing_evidence(**kwargs):
        smoothing_calls.append(kwargs)
        return None

    monkeypatch.setattr(contribution_service, "_build_contribution_smoothing_evidence", build_smoothing_evidence)
    monkeypatch.setattr(contribution_service, "_record_period_timeseries_total_delta", lambda **_kwargs: 0)
    monkeypatch.setattr(
        contribution_service,
        "_build_period_average_weight_methodology_status",
        lambda **_kwargs: AverageWeightMethodologyStatus(
            status="PROMOTED",
            max_shadow_delta_bp=125,
            is_material_shadow=True,
            is_cutover_candidate=True,
            is_promoted=True,
        ),
    )

    result = contribution_service._build_flat_period_contribution_result(
        request=request,
        period=period,
        daily_contributions_df=pd.DataFrame(),
        portfolio_results_df=pd.DataFrame(),
        reset_aware_average_weight_mode="candidate_periods",
        average_weight_audit_state=audit_state,
    )

    assert result is not None
    assert result.period_name == "QTD"
    assert result.average_weight_sum_residual_bp == 12
    assert result.result.total_portfolio_return == pytest.approx(3.48)
    assert result.result.total_contribution == 3.48
    assert result.result.average_weight_methodology_status is not None
    assert result.result.average_weight_methodology_status.is_promoted is True
    assert audit_state.delta_positions == 2
    assert residual_calls[0]["selected_average_weight_source_column"] == "reset_aware_average_weight_shadow"
    assert residual_calls[0]["residual_allocation_weight_column"] == "selected_average_weight"
    assert smoothing_calls[0]["residual_allocation_basis"] == "reset_aware_average_weight_shadow"


def test_build_flat_contribution_position_assembly_preserves_reset_aware_weighting(monkeypatch):
    period_slice_df = pd.DataFrame({"position_id": ["A"], "smoothed_contribution": [0.01]})
    totals_df = pd.DataFrame({"position_id": ["A"], "selected_average_weight": [0.5]})
    average_weight_shadow_df = pd.DataFrame(
        {
            "position_id": ["A"],
            "average_weight": [0.4],
            "reset_aware_average_weight_shadow": [0.5],
        }
    )
    methodology_context = SimpleNamespace(average_weight_shadow_df=average_weight_shadow_df)
    period = SimpleNamespace(name="QTD", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31))
    request = SimpleNamespace(
        smoothing=SimpleNamespace(method="CARINO"),
        emit=SimpleNamespace(timeseries=True, by_position_timeseries=True),
    )
    residual_calls: list[dict[str, object]] = []
    contribution_calls: list[dict[str, object]] = []
    series_calls: list[dict[str, object]] = []
    position_contributions = [
        PositionContribution(
            position_id="A",
            total_contribution=3.48,
            average_weight=50.0,
            total_return=6.96,
        )
    ]

    monkeypatch.setattr(
        contribution_service,
        "_select_period_average_weight_column",
        lambda **_kwargs: ("reset_aware_average_weight_shadow", True),
    )

    def build_residual_adjusted_position_totals(**kwargs):
        residual_calls.append(kwargs)
        return SimpleNamespace(totals_df=totals_df, residual_allocation_applied=True)

    def build_position_contributions(**kwargs):
        contribution_calls.append(kwargs)
        return position_contributions

    def build_period_series_outputs(**kwargs):
        series_calls.append(kwargs)
        return (["position-series"], ["daily-series"], ["emitted-position-series"])

    monkeypatch.setattr(
        contribution_service,
        "build_residual_adjusted_position_totals",
        build_residual_adjusted_position_totals,
    )
    monkeypatch.setattr(contribution_service, "build_position_contributions", build_position_contributions)
    monkeypatch.setattr(contribution_service, "_build_period_contribution_series_outputs", build_period_series_outputs)

    result = contribution_service._build_flat_contribution_position_assembly(
        request=request,
        period=period,
        period_slice_df=period_slice_df,
        period_methodology_context=methodology_context,
        reset_aware_average_weight_mode="candidate_periods",
        total_portfolio_return=0.0348,
    )

    assert result.selected_average_weight_column == "reset_aware_average_weight_shadow"
    assert result.use_reset_aware_average_weight is True
    assert result.position_contributions == position_contributions
    assert result.daily_series == ["daily-series"]
    assert result.emitted_position_series == ["emitted-position-series"]
    assert result.residual_allocation_applied is True
    assert residual_calls[0]["average_weight_df"] is average_weight_shadow_df
    assert residual_calls[0]["selected_average_weight_source_column"] == "reset_aware_average_weight_shadow"
    assert residual_calls[0]["residual_allocation_weight_column"] == "selected_average_weight"
    assert contribution_calls[0]["totals_df"] is totals_df
    assert contribution_calls[0]["period_start_date"] == date(2026, 1, 1)
    assert contribution_calls[0]["period_end_date"] == date(2026, 3, 31)
    assert contribution_calls[0]["average_weight_column"] == "selected_average_weight"
    assert series_calls[0]["position_contributions"] == position_contributions
    assert series_calls[0]["emit_timeseries"] is True
    assert series_calls[0]["emit_by_position_timeseries"] is True


def test_build_hierarchy_contribution_position_assembly_preserves_hierarchy_projection(monkeypatch):
    period_slice_df = pd.DataFrame({"position_id": ["A"], "sector": ["Technology"], "smoothed_contribution": [0.01]})
    totals_df = pd.DataFrame({"position_id": ["A"], "selected_average_weight": [0.5]})
    average_weight_shadow_df = pd.DataFrame(
        {
            "position_id": ["A"],
            "average_weight": [0.4],
            "reset_aware_average_weight_shadow": [0.5],
        }
    )
    methodology_context = SimpleNamespace(average_weight_shadow_df=average_weight_shadow_df)
    period = SimpleNamespace(name="ITD", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31))
    request = SimpleNamespace(
        smoothing=SimpleNamespace(method="CARINO"),
        emit=SimpleNamespace(timeseries=True, by_position_timeseries=True),
        hierarchy=["sector"],
    )
    residual_calls: list[dict[str, object]] = []
    contribution_calls: list[dict[str, object]] = []
    series_calls: list[dict[str, object]] = []
    hierarchy_calls: list[dict[str, object]] = []
    position_contributions = [
        PositionContribution(
            position_id="A",
            total_contribution=2.0,
            average_weight=50.0,
            total_return=4.0,
        )
    ]

    def build_residual_adjusted_position_totals(**kwargs):
        residual_calls.append(kwargs)
        return SimpleNamespace(totals_df=totals_df, residual_allocation_applied=True)

    def build_position_contributions(**kwargs):
        contribution_calls.append(kwargs)
        return position_contributions

    def build_period_series_outputs(**kwargs):
        series_calls.append(kwargs)
        return (["position-series"], ["daily-series"], ["emitted-position-series"])

    def build_hierarchy(**kwargs):
        hierarchy_calls.append(kwargs)
        return {
            "summary": {"portfolio_contribution": 2.0},
            "levels": [{"level": 1, "name": "sector", "rows": []}],
        }

    monkeypatch.setattr(
        contribution_service,
        "build_residual_adjusted_position_totals",
        build_residual_adjusted_position_totals,
    )
    monkeypatch.setattr(contribution_service, "build_position_contributions", build_position_contributions)
    monkeypatch.setattr(contribution_service, "_build_period_contribution_series_outputs", build_period_series_outputs)
    monkeypatch.setattr(contribution_service, "_build_hierarchy_from_adjusted_position_series", build_hierarchy)
    monkeypatch.setattr(
        contribution_service,
        "_select_period_average_weight_column",
        lambda **_kwargs: ("reset_aware_average_weight_shadow", True),
    )

    result = contribution_service._build_hierarchy_contribution_position_assembly(
        request=request,
        period=period,
        period_slice_df=period_slice_df,
        period_methodology_context=methodology_context,
        reset_aware_average_weight_mode="candidate_periods",
        total_portfolio_return=0.02,
    )

    assert result.selected_average_weight_column == "reset_aware_average_weight_shadow"
    assert result.use_reset_aware_average_weight is True
    assert result.position_contributions == position_contributions
    assert result.daily_series == ["daily-series"]
    assert result.emitted_position_series == ["emitted-position-series"]
    assert result.hierarchy_results["summary"]["portfolio_contribution"] == pytest.approx(2.0)
    assert result.hierarchy_results["levels"][0]["name"] == "sector"
    assert result.residual_allocation_applied is True
    assert residual_calls[0]["average_weight_df"] is average_weight_shadow_df
    assert residual_calls[0]["average_weight_columns"] == ["average_weight", "reset_aware_average_weight_shadow"]
    assert residual_calls[0]["residual_allocation_weight_column"] == "selected_average_weight"
    assert residual_calls[0]["selected_average_weight_source_column"] == "reset_aware_average_weight_shadow"
    assert contribution_calls[0]["totals_df"] is totals_df
    assert contribution_calls[0]["period_start_date"] == date(2026, 1, 1)
    assert contribution_calls[0]["period_end_date"] == date(2026, 3, 31)
    assert contribution_calls[0]["average_weight_column"] == "selected_average_weight"
    assert series_calls[0]["force_position_series"] is True
    assert hierarchy_calls[0]["period_slice_df"] is period_slice_df
    assert hierarchy_calls[0]["position_series"] == ["position-series"]
    pd.testing.assert_frame_equal(hierarchy_calls[0]["position_average_weights"], totals_df)
    assert hierarchy_calls[0]["request"] is request


def test_build_hierarchy_period_contribution_result_preserves_hierarchy_outputs(monkeypatch):
    period_slice_df = pd.DataFrame({"position_id": ["A"], "smoothed_contribution": [0.01]})
    portfolio_period_slice_df = pd.DataFrame({"portfolio_id": ["P"]})
    totals_df = pd.DataFrame({"position_id": ["A"], "selected_average_weight": [0.5]})
    period = SimpleNamespace(name="ITD", start_date=date(2026, 1, 1), end_date=date(2026, 3, 31))
    request = SimpleNamespace(
        smoothing=SimpleNamespace(method="CARINO"),
        emit=SimpleNamespace(timeseries=True, by_position_timeseries=True),
        hierarchy=["sector"],
    )
    audit_state = AverageWeightShadowAuditState()
    residual_calls: list[dict[str, object]] = []
    hierarchy_calls: list[dict[str, object]] = []
    smoothing_calls: list[dict[str, object]] = []
    methodology_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        contribution_service,
        "_slice_contribution_period_frames",
        lambda **_kwargs: SimpleNamespace(
            period_slice_df=period_slice_df,
            portfolio_period_slice_df=portfolio_period_slice_df,
        ),
    )
    monkeypatch.setattr(
        contribution_service,
        "_build_contribution_period_methodology_context",
        lambda **_kwargs: SimpleNamespace(
            delta_positions=1,
            max_shadow_delta_bp=25,
            sum_shadow_delta_bp=25,
            average_weight_shadow_df=pd.DataFrame(
                {
                    "position_id": ["A"],
                    "average_weight": [0.5],
                    "reset_aware_average_weight_shadow": [0.5],
                }
            ),
            position_flow_balance_counts={"position_flow_residual_days": 0},
            portfolio_reset_without_position_reset_days=0,
            position_reset_without_portfolio_reset_days=0,
        ),
    )
    monkeypatch.setattr(contribution_service, "_calculate_reset_aware_period_portfolio_return", lambda *_args: 0.02)
    monkeypatch.setattr(
        contribution_service,
        "_select_period_average_weight_column",
        lambda **_kwargs: ("average_weight", False),
    )

    def build_residual_adjusted_position_totals(**kwargs):
        residual_calls.append(kwargs)
        return SimpleNamespace(totals_df=totals_df, residual_allocation_applied=True)

    monkeypatch.setattr(
        contribution_service,
        "build_residual_adjusted_position_totals",
        build_residual_adjusted_position_totals,
    )
    monkeypatch.setattr(
        contribution_service,
        "build_position_contributions",
        lambda **_kwargs: [
            PositionContribution(
                position_id="A",
                total_contribution=2.0,
                average_weight=50.0,
                total_return=4.0,
            )
        ],
    )
    monkeypatch.setattr(
        contribution_service,
        "_build_period_contribution_series_outputs",
        lambda **_kwargs: ([], [], []),
    )
    monkeypatch.setattr(contribution_service, "_calculate_average_weight_sum_residual_bp", lambda _rows: 3)

    def build_hierarchy(**kwargs):
        hierarchy_calls.append(kwargs)
        return {
            "summary": {
                "portfolio_contribution": 2.0,
                "coverage_mv_pct": 100.0,
                "weighting_scheme": "average_weight",
            },
            "levels": [{"level": 1, "name": "sector", "rows": []}],
        }

    monkeypatch.setattr(contribution_service, "_build_hierarchy_from_adjusted_position_series", build_hierarchy)

    def build_smoothing_evidence(**kwargs):
        smoothing_calls.append(kwargs)
        return None

    monkeypatch.setattr(contribution_service, "_build_contribution_smoothing_evidence", build_smoothing_evidence)
    monkeypatch.setattr(contribution_service, "_record_period_timeseries_total_delta", lambda **_kwargs: 0)

    def build_methodology_status(**kwargs):
        methodology_calls.append(kwargs)
        return AverageWeightMethodologyStatus(
            status="OK",
            max_shadow_delta_bp=25,
            is_material_shadow=False,
            is_cutover_candidate=False,
            is_promoted=False,
        )

    monkeypatch.setattr(
        contribution_service, "_build_period_average_weight_methodology_status", build_methodology_status
    )

    result = contribution_service._build_hierarchy_period_contribution_result(
        request=request,
        period=period,
        daily_contributions_df=pd.DataFrame(),
        portfolio_results_df=pd.DataFrame(),
        reset_aware_average_weight_mode="candidate_periods",
        average_weight_audit_state=audit_state,
    )

    assert result is not None
    assert result.period_name == "ITD"
    assert result.average_weight_sum_residual_bp == 3
    assert result.result.total_portfolio_return == pytest.approx(2.0)
    assert result.result.total_contribution == pytest.approx(2.0)
    assert result.result.summary is not None
    assert result.result.summary.portfolio_contribution == pytest.approx(2.0)
    assert result.result.summary.coverage_mv_pct == pytest.approx(100.0)
    assert result.result.levels is not None
    assert result.result.levels[0].name == "sector"
    assert audit_state.delta_positions == 1
    assert residual_calls[0]["average_weight_columns"] == ["average_weight", "reset_aware_average_weight_shadow"]
    assert residual_calls[0]["residual_allocation_weight_column"] == "selected_average_weight"
    assert residual_calls[0]["selected_average_weight_source_column"] == "average_weight"
    assert hierarchy_calls[0]["request"] is request
    assert smoothing_calls[0]["residual_allocation_basis"] == "average_weight"
    assert methodology_calls[0]["is_promoted"] is False
