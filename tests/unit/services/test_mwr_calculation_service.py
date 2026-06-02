from datetime import date

import pytest

from app.models.mwr_requests import CashFlow, MoneyWeightedReturnRequest
from app.services.mwr_calculation_service import calculate_mwr_result
from engine.mwr import calculate_money_weighted_return


def test_calculate_mwr_result_matches_engine_result():
    request = MoneyWeightedReturnRequest.model_validate(
        {
            "portfolio_id": "MWR-SERVICE",
            "begin_mv": 100000.0,
            "end_mv": 115000.0,
            "as_of": "2025-12-31",
            "cash_flows": [
                {"amount": 10000.0, "date": "2025-03-15"},
                {"amount": -5000.0, "date": "2025-09-20"},
            ],
            "mwr_method": "DIETZ",
        }
    )

    service_result = calculate_mwr_result(request)
    engine_result = calculate_money_weighted_return(
        begin_mv=request.begin_mv,
        end_mv=request.end_mv,
        cash_flows=request.cash_flows,
        calculation_method=request.mwr_method,
        annualization=request.annualization,
        as_of=request.as_of,
        start_date=request.start_date,
        solver=request.solver,
    )

    assert service_result.mwr == pytest.approx(engine_result.mwr)
    assert service_result.method == engine_result.method
    assert service_result.start_date == engine_result.start_date
    assert service_result.end_date == engine_result.end_date


def test_calculate_mwr_result_passes_request_cashflows():
    request = MoneyWeightedReturnRequest.model_validate(
        {
            "portfolio_id": "MWR-SERVICE-CASHFLOWS",
            "begin_mv": 100.0,
            "end_mv": 130.0,
            "as_of": "2025-12-31",
            "cash_flows": [{"amount": 10.0, "date": "2025-06-30"}],
            "mwr_method": "MODIFIED_DIETZ",
        }
    )

    result = calculate_mwr_result(request)

    assert request.cash_flows == [CashFlow(amount=10.0, date=date(2025, 6, 30))]
    assert result.method == "MODIFIED_DIETZ"
