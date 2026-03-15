# engine/mwr.py
from datetime import date
from typing import List, Literal

import numpy as np
from scipy.optimize import brentq

from app.models.mwr_requests import CashFlow
from app.models.mwr_responses import Convergence, MWRResult
from core.envelope import Annualization


def _xirr(values: np.ndarray, dates: np.ndarray) -> dict:
    """Calculates XIRR using the Brent method for root-finding."""
    if np.all(values >= 0) or np.all(values <= 0):
        return {"rate": None, "converged": False, "notes": "No sign change in cash flows."}

    t0 = dates.min()
    time_diffs = np.array([(d - t0).days / 365.25 for d in dates])

    def npv_func(rate):
        return np.sum(values / ((1 + rate) ** time_diffs))

    try:
        rate = brentq(npv_func, -0.99, 100.0)
        return {"rate": rate, "converged": True, "notes": "XIRR calculation successful."}
    except (RuntimeError, ValueError) as e:
        return {"rate": None, "converged": False, "notes": f"XIRR failed to converge: {e}"}


def calculate_money_weighted_return(
    begin_mv: float,
    end_mv: float,
    cash_flows: List[CashFlow],
    calculation_method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"],
    annualization: Annualization,
    as_of: date,
    start_date: date | None = None,
) -> MWRResult:
    """
    Orchestrates the MWR calculation using the specified method and fallback logic.
    Returns a simple MWRResult data object.
    """
    notes = []
    all_dates = [cf.date for cf in cash_flows]
    if start_date is None:
        if not all_dates:
            start_date = as_of
        else:
            start_date = min(all_dates)
    end_date = as_of

    if calculation_method == "XIRR":
        xirr_start_date = start_date
        dates = [xirr_start_date] + [cf.date for cf in cash_flows] + [end_date]
        values = [-begin_mv] + [-cf.amount for cf in cash_flows] + [end_mv]

        xirr_result = _xirr(np.array(values), np.array(dates))
        if xirr_result["converged"]:
            rate = xirr_result["rate"]
            notes.append(xirr_result["notes"])
            return MWRResult(
                mwr=rate * 100,
                mwr_annualized=rate * 100,
                method="XIRR",
                start_date=xirr_start_date,
                end_date=end_date,
                notes=notes,
                convergence=Convergence(converged=True),
            )
        notes.append(xirr_result["notes"])
        notes.append("XIRR failed, falling back to Simple Dietz.")

    net_cash_flow = sum(cf.amount for cf in cash_flows)
    denominator = begin_mv + (net_cash_flow / 2)
    if denominator == 0:
        notes.append("Calculation resulted in a zero denominator.")
        return MWRResult(mwr=0.0, method="DIETZ", start_date=start_date, end_date=end_date, notes=notes)

    numerator = end_mv - begin_mv - net_cash_flow
    periodic_rate = numerator / denominator

    mwr_annualized = None
    if annualization.enabled:
        days_in_period = (end_date - start_date).days if end_date > start_date else 0
        if days_in_period > 0:
            ppy = 365.25 if annualization.basis == "ACT/ACT" else 365.0
            scale = ppy / days_in_period
            mwr_annualized = ((1 + periodic_rate) ** scale - 1) * 100

    return MWRResult(
        mwr=periodic_rate * 100,
        mwr_annualized=mwr_annualized,
        method="DIETZ",
        start_date=start_date,
        end_date=end_date,
        notes=notes,
    )
