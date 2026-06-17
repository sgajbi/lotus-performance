from datetime import date
from uuid import uuid4

from app.models.requests import Analysis, DailyInputData, PerformanceRequest
from app.models.responses import PerformanceResponse
from app.services.inspection.twr_inspection_service import (
    _response_master_window_values,
    _scope_request_to_response_master_window,
    _valuation_points_in_window,
)


def test_scope_request_to_response_master_window_uses_executed_twr_period():
    response = PerformanceResponse.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "input_mode": "stateful",
            "results_by_period": {
                "YTD": {
                    "portfolio": {
                        "summary": {
                            "period_return": {"base": 1.0, "local": 1.0, "fx": 0.0},
                            "cumulative_return": {"base": 1.0, "local": 1.0, "fx": 0.0},
                        },
                        "breakdowns": {
                            "daily": [
                                {
                                    "period": "2026-01-01",
                                    "period_start": "2026-01-01",
                                    "period_end": "2026-01-01",
                                    "period_return": {"base": 1.0, "local": 1.0, "fx": 0.0},
                                    "cumulative_return": {"base": 1.0, "local": 1.0, "fx": 0.0},
                                }
                            ]
                        },
                    }
                }
            },
            "calculation_supportability": {
                "state": "ready",
                "reason": "calculation_complete",
                "freshness_bucket": "current",
                "input_row_count": 375,
                "resolved_period_count": 1,
                "benchmark_row_count": 0,
            },
            "meta": {
                "calculation_id": str(uuid4()),
                "engine_version": "1.0.0",
                "precision_mode": "FLOAT64",
                "annualization": {"enabled": False},
                "calendar": {"type": "BUSINESS"},
                "periods": {
                    "requested": ["YTD"],
                    "master_start": "2026-01-01",
                    "master_end": "2026-04-10",
                },
            },
            "diagnostics": {
                "nip_days": 0,
                "reset_days": 0,
                "effective_period_start": "2026-01-01",
            },
            "audit": {"counts": {"input_rows": 375}},
        }
    )
    request = PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2025, 1, 6),
        metric_basis="NET",
        report_end_date=date(2026, 4, 10),
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(
                perf_date=date(2025, 4, 12),
                begin_mv=26239.6,
                end_mv=821914.6,
            ),
            DailyInputData(
                perf_date=date(2026, 1, 1),
                begin_mv=1000.0,
                end_mv=1000.14,
            ),
        ],
    )

    scoped = _scope_request_to_response_master_window(request, response)

    assert scoped is not None
    assert scoped.performance_start_date == date(2026, 1, 1)
    assert scoped.report_end_date == date(2026, 4, 10)
    assert [point.perf_date for point in scoped.valuation_points] == [date(2026, 1, 1)]


def test_valuation_points_in_window_includes_boundaries_and_omits_outside_points():
    points = [
        DailyInputData(perf_date=date(2025, 12, 31), begin_mv=900.0, end_mv=950.0),
        DailyInputData(perf_date=date(2026, 1, 1), begin_mv=1000.0, end_mv=1001.0),
        DailyInputData(perf_date=date(2026, 1, 2), begin_mv=1001.0, end_mv=1002.0),
        DailyInputData(perf_date=date(2026, 1, 3), begin_mv=1002.0, end_mv=1003.0),
    ]

    scoped_points = _valuation_points_in_window(
        points,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )

    assert [point.perf_date for point in scoped_points] == [date(2026, 1, 1), date(2026, 1, 2)]


def test_response_master_window_values_reads_only_string_master_bounds():
    assert _response_master_window_values(
        _response_with_periods({"master_start": "2026-01-01", "master_end": "2026-01-02"})
    ) == ("2026-01-01", "2026-01-02")
    assert _response_master_window_values(_response_with_periods({"master_start": "2026-01-01"})) is None
    assert (
        _response_master_window_values(_response_with_periods({"master_start": "2026-01-01", "master_end": 7})) is None
    )
    assert _response_master_window_values(_response_with_periods(["2026-01-01", "2026-01-02"])) is None


def _response_with_periods(periods):
    return type(
        "ResponseWithPeriods",
        (),
        {"meta": type("MetaWithPeriods", (), {"periods": periods})()},
    )()
