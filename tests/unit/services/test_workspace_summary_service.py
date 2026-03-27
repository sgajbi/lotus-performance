from types import SimpleNamespace
from uuid import uuid4

import pandas as pd

from app.models.requests import DailyInputData
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.services.workspace_summary_service import WorkspaceTWRArtifacts, calculate_workspace_summary
from core.envelope import Diagnostics


def test_workspace_summary_stateful_retrieval_uses_longest_requested_window(mocker):
    captured: dict[str, object] = {}
    mocker.patch(
        "app.services.workspace_summary_service.get_settings",
        return_value=SimpleNamespace(APP_VERSION="test-version"),
    )
    mocker.patch(
        "app.services.workspace_summary_service.generate_canonical_hash",
        return_value=("fingerprint", "hash"),
    )
    mocker.patch("app.services.workspace_summary_service.execution_registry.mark_running")
    mocker.patch("app.services.workspace_summary_service.execution_registry.start_stage")
    mocker.patch("app.services.workspace_summary_service.execution_registry.complete_stage")
    mocker.patch("app.services.workspace_summary_service.complete_execution_with_lineage")
    mocker.patch("app.services.workspace_summary_service.build_workspace_contribution_artifacts", return_value=None)
    mocker.patch("app.services.workspace_summary_service.build_workspace_attribution_artifacts", return_value=None)
    mocker.patch(
        "app.services.workspace_summary_service.retrieve_stateful_portfolio_input",
        side_effect=lambda **kwargs: (
            captured.update({"start_date": kwargs["start_date"]})
            or SimpleNamespace(retrieval_metadata=SimpleNamespace(chunk_count=3, page_count=7))
        ),
    )
    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_portfolio_valuation_input",
        return_value=SimpleNamespace(
            performance_start_date=pd.Timestamp("2026-01-01").date(),
            observations=[{"perf_date": "2026-05-30"}],
            valuation_points=[
                {
                    "perf_date": "2026-05-30",
                    "begin_mv": 100.0,
                    "bod_cf": 0.0,
                    "eod_cf": 0.0,
                    "mgmt_fees": 0.0,
                    "end_mv": 101.0,
                },
                {
                    "perf_date": "2026-06-30",
                    "begin_mv": 101.0,
                    "bod_cf": 0.0,
                    "eod_cf": 0.0,
                    "mgmt_fees": 0.0,
                    "end_mv": 102.0,
                },
            ],
        ),
    )
    mocker.patch(
        "app.services.workspace_summary_service._calculate_workspace_twr_artifacts",
        return_value=WorkspaceTWRArtifacts(
            daily_results_df=pd.DataFrame(
                {
                    "perf_date": [pd.Timestamp("2026-05-30").date(), pd.Timestamp("2026-06-30").date()],
                    "daily_ror": [1.0, 0.990099],
                    "perf_reset": [False, False],
                    "final_cum_ror": [1.0, 2.0],
                }
            ),
            diagnostics=Diagnostics(
                nip_days=0,
                reset_days=0,
                effective_period_start=pd.Timestamp("2026-05-30").date(),
                notes=[],
            ),
        ),
    )

    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
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

    response = calculate_workspace_summary(request)

    assert str(captured["start_date"]) == "2026-05-31"
    assert response.audit.counts["portfolio_chunk_count"] == 3
    assert set(response.results_by_period) == {"1D", "1M"}
    one_day = response.results_by_period["1D"]
    assert (
        one_day.portfolio_twr.net.summary.period_return.base == one_day.portfolio_twr.net.summary.cumulative_return.base
    )
    assert one_day.money_weighted_return.period_return == one_day.money_weighted_return.cumulative_return


def test_workspace_summary_stateful_linked_benchmark_resolves_assignment_once(mocker):
    captured: dict[str, object] = {}
    mocker.patch(
        "app.services.workspace_summary_service.get_settings",
        return_value=SimpleNamespace(APP_VERSION="test-version"),
    )
    mocker.patch(
        "app.services.workspace_summary_service.generate_canonical_hash",
        return_value=("fingerprint", "hash"),
    )
    mocker.patch("app.services.workspace_summary_service.execution_registry.mark_running")
    mocker.patch("app.services.workspace_summary_service.execution_registry.start_stage")
    mocker.patch("app.services.workspace_summary_service.execution_registry.complete_stage")
    mocker.patch("app.services.workspace_summary_service.complete_execution_with_lineage")
    mocker.patch("app.services.workspace_summary_service.build_workspace_contribution_artifacts", return_value=None)
    mocker.patch("app.services.workspace_summary_service.build_workspace_attribution_artifacts", return_value=None)
    mocker.patch(
        "app.services.workspace_summary_service._resolve_workspace_portfolio_input",
        return_value=SimpleNamespace(
            input_mode="stateful",
            performance_start_date=pd.Timestamp("2025-01-01").date(),
            valuation_points=[
                DailyInputData.model_validate(
                    {
                        "perf_date": "2026-01-02",
                        "begin_mv": 100.0,
                        "bod_cf": 0.0,
                        "eod_cf": 0.0,
                        "mgmt_fees": 0.0,
                        "end_mv": 101.0,
                    }
                )
            ],
            observations=[{"perf_date": "2026-01-02"}],
            source_details={"portfolio_chunk_count": 2, "portfolio_page_count": 4},
        ),
    )

    async def _get_benchmark_assignment(**kwargs):
        captured["assignment_called"] = True
        return (200, {"benchmark_id": "LINKED-BMK"})

    stateful_input_service = SimpleNamespace(
        get_benchmark_assignment=_get_benchmark_assignment,
    )
    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_input_service",
        return_value=stateful_input_service,
    )

    async def _build_benchmark_input(**kwargs):
        captured["benchmark_id"] = kwargs["benchmark_id"]
        return SimpleNamespace(
            benchmark_currency="USD",
            component_observations=[
                SimpleNamespace(
                    model_dump=lambda mode="python": {
                        "component_id": "IDX1",
                        "perf_date": "2026-01-02",
                        "weight_bop": 1.0,
                        "component_return": 0.01,
                    }
                )
            ],
            benchmark_return_points=[],
            source_details={"chunk_count": 5},
        )

    mocker.patch(
        "app.services.workspace_summary_service.build_stateful_benchmark_input", side_effect=_build_benchmark_input
    )
    mocker.patch(
        "app.services.workspace_summary_service._calculate_workspace_twr_artifacts",
        return_value=WorkspaceTWRArtifacts(
            daily_results_df=pd.DataFrame(
                {
                    "perf_date": [pd.Timestamp("2026-01-02").date()],
                    "daily_ror": [1.0],
                    "perf_reset": [False],
                    "final_cum_ror": [1.0],
                }
            ),
            diagnostics=Diagnostics(
                nip_days=0,
                reset_days=0,
                effective_period_start=pd.Timestamp("2026-01-02").date(),
                notes=[],
            ),
        ),
    )

    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT-1",
            "report_end_date": "2026-01-02",
            "performance_start_date": "2025-01-01",
            "input_mode": "stateful",
            "stateful_input": {},
            "periods": [{"period": "1D", "frequencies": ["daily"]}],
            "include_benchmark": True,
            "benchmark": {"input_mode": "stateful", "stateful_input": {}},
        }
    )

    response = calculate_workspace_summary(request)

    assert captured["assignment_called"] is True
    assert captured["benchmark_id"] == "LINKED-BMK"
    assert response.results_by_period["1D"].benchmark.benchmark_id == "LINKED-BMK"
    assert (
        response.results_by_period["1D"].benchmark.summary.period_return.base
        == response.results_by_period["1D"].benchmark.summary.cumulative_return.base
    )
    assert response.audit.counts["benchmark_chunk_count"] == 5
