"""Exact monetary translation under an admitted daily method, using the shipped member engine."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import pandas as pd

from app.models.composite_materialization import (
    CompositeNormalizedAssetEvidence,
    CompositeNormalizedCashFlow,
    CompositeNormalizedMemberSourceEvidence,
)
from engine.compute import run_calculations
from engine.config import EngineConfig, PrecisionMode
from engine.numerical_boundary import monetary_arithmetic_context
from engine.schema import PortfolioColumns as C


def normalize_member_money(command, native, admitted, *, member_id, fx_snapshots):
    member = _require_native_member(native, admitted, member_id)
    points, assets = _native_window(command, native)
    rates = _MemberFixings(member.conversion_kind, {row.fixing_date: Decimal(row.rate) for row in member.fixings})
    _require_engine_fixings(command, native, member, assets, rates)
    _require_linked_member_return(command, native, points)
    converted, flows, fees = _normalized_daily_money(assets, points, rates)
    return CompositeNormalizedMemberSourceEvidence(
        native_evidence=native,
        normalization_binding=command.currency_normalization_binding,
        verification_receipt=admitted.verification_receipt,
        normalized_assets=CompositeNormalizedAssetEvidence(
            reporting_currency=command.reporting_currency, observations=converted
        ),
        normalized_cash_flows=flows,
        normalized_management_fees=fees,
        fx_snapshots=fx_snapshots,
    )


def _require_native_member(native, admitted, member_id):
    member = next((row for row in admitted.source.members if row.member_id == member_id), None)
    request = native.calculation_request.portfolio
    if member is None or (member.input_fingerprint, member.calculation_hash, member.source_money_currency) != (
        native.input_fingerprint,
        native.calculation_hash,
        native.source_assets.portfolio_currency,
    ):
        raise ValueError("Normalization member and native input identities differ")
    if request.currency != member.source_money_currency or request.hedging is not None:
        raise ValueError("Native currency or hedging is incompatible with the admitted method")
    return member


def _native_window(command, native):
    request = native.calculation_request.portfolio
    points = [row for row in request.valuation_points if command.period_start <= row.perf_date <= command.period_end]
    assets = native.source_assets.observations
    _require_daily_window(command, points, assets)
    _require_native_money(points, assets)
    return points, assets


def _require_daily_window(command, points, assets):
    dates = [row.valuation_date for row in assets]
    if [row.perf_date for row in points] != dates or len(dates) != (command.period_end - command.period_start).days + 1:
        raise ValueError("The admitted natural-daily method requires a complete exact daily native window")
    if any(Decimal(str(row.bod_cf)) != 0 for row in points):
        raise ValueError("Beginning-of-day flow fixing semantics are unavailable for this method")


def _require_native_money(points, assets):
    if any(
        (Decimal(str(point.begin_mv)), Decimal(str(point.end_mv)))
        != (asset.beginning_market_value, asset.ending_market_value)
        for point, asset in zip(points, assets, strict=True)
    ):
        raise ValueError("Native valuation and retained request money disagree")


@dataclass(frozen=True)
class _MemberFixings:
    conversion_kind: str
    lookup: dict[str, Decimal]

    def rate(self, day):
        if self.conversion_kind == "IDENTITY":
            return Decimal(1)
        if day.isoformat() not in self.lookup:
            raise ValueError("An exact economic-date fixing is unavailable")
        return self.lookup[day.isoformat()]


def _require_engine_fixings(command, native, member, assets, rates):
    if member.conversion_kind != "DIRECT":
        return
    request = native.calculation_request.portfolio
    engine_rates = _unique_engine_rates(_require_applied_reporting_fx(request, command.reporting_currency).rates)
    dates = [row.valuation_date for row in assets]
    for day in set(dates + [day - timedelta(days=1) for day in dates]):
        if engine_rates.get((member.source_money_currency, day)) != rates.rate(day):
            raise ValueError("Member engine fixing differs from independently admitted source evidence")


def _require_applied_reporting_fx(request, reporting_currency):
    if request.currency_mode != "BOTH" or request.report_ccy != reporting_currency or request.fx is None:
        raise ValueError("The retained member engine did not apply the required reporting currency")
    return request.fx


def _unique_engine_rates(rates):
    result = {}
    for row in rates:
        key = (row.ccy, row.date)
        if key in result:
            raise ValueError("Ambiguous retained member FX fixing")
        result[key] = Decimal(str(row.rate))
    return result


def _require_linked_member_return(command, native, points):
    calculated = _recalculate_member_daily_returns(command, native, points)
    linked = Decimal(1)
    with monetary_arithmetic_context([*calculated], products=True):
        for value in calculated:
            linked *= 1 + value
    if abs(linked - 1 - native.period_return) > Decimal("1e-10"):
        raise ValueError("Retained period return does not reconcile to the existing member engine")


def _normalized_daily_money(assets, points, rates):
    converted, flows, fees = [], [], []
    for asset, point in zip(assets, points, strict=True):
        day = asset.valuation_date
        beginning_rate, ending_rate = rates.rate(day - timedelta(days=1)), rates.rate(day)
        converted.append(_normalized_asset(asset, beginning_rate, ending_rate))
        flows.append(_normalized_cash_flow(day, point.eod_cf, ending_rate))
        fees.append(_normalized_cash_flow(day, point.mgmt_fees, ending_rate))
    return converted, flows, fees


def _normalized_asset(asset, beginning_rate, ending_rate):
    with monetary_arithmetic_context(
        [asset.beginning_market_value, asset.ending_market_value, beginning_rate, ending_rate], products=True
    ):
        return {
            "valuation_date": asset.valuation_date,
            "beginning_market_value": asset.beginning_market_value * beginning_rate,
            "ending_market_value": asset.ending_market_value * ending_rate,
        }


def _normalized_cash_flow(day, amount, rate):
    money = Decimal(str(amount))
    with monetary_arithmetic_context([money, rate], products=True):
        return CompositeNormalizedCashFlow(
            business_date=day,
            placement="END_OF_DAY",
            native_amount=money,
            reporting_amount=money * rate,
            fixing_date=day,
            rate=rate,
        )


def _recalculate_member_daily_returns(command, native, points):
    request = native.calculation_request.portfolio
    precision = PrecisionMode(native.precision_mode)
    number = Decimal if precision == PrecisionMode.DECIMAL_STRICT else float
    frame = _daily_member_frame(command, points, number)
    config = EngineConfig(
        performance_start_date=command.period_start,
        report_end_date=command.period_end,
        metric_basis=request.metric_basis,
        period_type="YTD",
        precision_mode=precision,
        rounding_precision=request.rounding_precision,
        currency_mode=request.currency_mode,
        source_currency=request.currency,
        report_ccy=request.report_ccy,
        fx=request.fx,
        hedging=request.hedging,
    )
    # Reuse the shipped reporting projection: FLOAT64 daily percentages are
    # rounded at the retained request precision before period linking. Native
    # monetary conversion remains exact and separate from this return projection.
    result, _ = run_calculations(frame, config)
    return [Decimal(str(value)) / 100 for value in result[C.DAILY_ROR.value]]


def _daily_member_frame(command, points, number):
    money_fields = {
        C.BEGIN_MV: "begin_mv",
        C.END_MV: "end_mv",
        C.BOD_CF: "bod_cf",
        C.EOD_CF: "eod_cf",
        C.MGMT_FEES: "mgmt_fees",
    }
    columns = {column: [number(str(getattr(row, field))) for row in points] for column, field in money_fields.items()}
    columns[C.PERF_DATE] = pd.to_datetime([row.perf_date for row in points])
    columns[C.EFFECTIVE_PERIOD_START_DATE] = pd.to_datetime([command.period_start] * len(points))
    return pd.DataFrame(columns)
