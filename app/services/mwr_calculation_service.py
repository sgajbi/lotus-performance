from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.models.mwr_responses import MWRResult
from engine.mwr import calculate_money_weighted_return


def calculate_mwr_result(request: MoneyWeightedReturnRequest) -> MWRResult:
    return calculate_money_weighted_return(
        begin_mv=request.begin_mv,
        end_mv=request.end_mv,
        cash_flows=request.cash_flows,
        calculation_method=request.mwr_method,
        annualization=request.annualization,
        as_of=request.as_of,
        start_date=request.start_date,
        solver=request.solver,
    )
