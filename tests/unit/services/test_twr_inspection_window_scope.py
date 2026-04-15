from datetime import date
from uuid import uuid4

from app.models.requests import Analysis, DailyInputData, PerformanceRequest
from app.models.responses import PerformanceResponse
from app.services.inspection.twr_inspection_service import _scope_request_to_response_master_window


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
