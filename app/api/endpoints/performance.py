# app/api/endpoints/performance.py
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from adapters.api_adapter import (
    create_engine_config,
    create_engine_dataframe,
    format_breakdowns_for_response,
)
from app.core.config import get_settings
from app.models.attribution_requests import AttributionRequest
from app.models.attribution_responses import AttributionResponse
from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.models.mwr_responses import MoneyWeightedReturnResponse
from app.models.requests import PerformanceRequest
from app.models.responses import (
    PerformanceResponse,
    PortfolioReturnDecomposition,
    ResetEvent,
    SinglePeriodPerformanceResult,
)
from app.services.lineage_service import lineage_service
from core.envelope import Audit, Diagnostics, Meta
from core.periods import resolve_periods
from core.repro import generate_canonical_hash
from engine.attribution import aggregate_attribution_results, run_attribution_calculations
from engine.breakdown import generate_performance_breakdowns
from engine.compute import run_calculations
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from engine.mwr import calculate_money_weighted_return
from engine.schema import PortfolioColumns

router = APIRouter(tags=["Performance"])
settings = get_settings()


def _as_numeric(value: object, default=0):
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return numeric


def _get_total_cum_ror(row: pd.Series | None, prefix: str = "") -> float:
    if row is None:
        return 0.0
    long_cum = _as_numeric(row.get(f"{prefix}long_cum_ror", 0))
    short_cum = _as_numeric(row.get(f"{prefix}short_cum_ror", 0))
    return ((1 + long_cum / 100) * (1 + short_cum / 100) - 1) * 100


def _calculate_total_return_from_reset_slice(
    df_slice: pd.DataFrame, daily_results_df: pd.DataFrame
) -> PortfolioReturnDecomposition:
    end_row = df_slice.iloc[-1]
    full_perf_dates = pd.to_datetime(daily_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
    slice_min_date = pd.to_datetime(df_slice[PortfolioColumns.PERF_DATE.value].min()).date()
    day_before_mask = full_perf_dates < slice_min_date
    day_before_row = daily_results_df[day_before_mask].iloc[-1] if day_before_mask.any() else None

    start_cum_base = _as_numeric(
        day_before_row[PortfolioColumns.FINAL_CUM_ROR.value] if day_before_row is not None else 0
    )
    end_cum_base = _as_numeric(end_row[PortfolioColumns.FINAL_CUM_ROR.value])

    start_base_denom = 1 + start_cum_base / 100
    if start_base_denom == 0:
        base_total = end_cum_base
    else:
        base_total = (((1 + end_cum_base / 100) / start_base_denom) - 1) * 100

    if "local_ror" not in df_slice.columns:
        return PortfolioReturnDecomposition(local=base_total, fx=0.0, base=base_total)

    start_cum_local = _get_total_cum_ror(day_before_row, "local_ror_")
    end_cum_local = _get_total_cum_ror(end_row, "local_ror_")

    start_local_denom = 1 + start_cum_local / 100
    if start_local_denom == 0:
        local_total = end_cum_local
    else:
        local_total = (((1 + end_cum_local / 100) / start_local_denom) - 1) * 100

    base_denom_for_fx = 1 + local_total / 100
    if base_denom_for_fx == 0:
        fx_total = 0.0
    else:
        fx_total = (((1 + base_total / 100) / base_denom_for_fx) - 1) * 100

    return PortfolioReturnDecomposition(local=local_total, fx=fx_total, base=base_total)


def _calculate_total_return_from_non_reset_slice(df_slice: pd.DataFrame) -> PortfolioReturnDecomposition:
    daily_ror = pd.to_numeric(df_slice[PortfolioColumns.DAILY_ROR.value], errors="coerce").fillna(0.0)
    base_total = _as_numeric(((1 + daily_ror / 100).prod() - 1) * 100)

    if "local_ror" not in df_slice.columns:
        return PortfolioReturnDecomposition(local=base_total, fx=0.0, base=base_total)

    local_ror = pd.to_numeric(df_slice["local_ror"], errors="coerce").fillna(0.0)
    local_total = _as_numeric(((1 + local_ror / 100).prod() - 1) * 100)
    base_denom_for_fx = 1 + local_total / 100
    if base_denom_for_fx == 0:
        fx_total = 0.0
    else:
        fx_total = _as_numeric((((1 + base_total / 100) / base_denom_for_fx) - 1) * 100)

    return PortfolioReturnDecomposition(local=local_total, fx=fx_total, base=base_total)


def _calculate_total_return_from_slice(
    df_slice: pd.DataFrame, daily_results_df: pd.DataFrame
) -> PortfolioReturnDecomposition:
    if df_slice.empty:
        return PortfolioReturnDecomposition(local=0.0, fx=0.0, base=0.0)

    if df_slice[PortfolioColumns.PERF_RESET.value].any():
        return _calculate_total_return_from_reset_slice(df_slice, daily_results_df)

    return _calculate_total_return_from_non_reset_slice(df_slice)


@router.post("/twr", response_model=PerformanceResponse, summary="Calculate Time-Weighted Return")
async def calculate_twr_endpoint(request: PerformanceRequest, background_tasks: BackgroundTasks):
    """
    Calculates time-weighted return (TWR) for one or more requested periods
    and provides performance breakdowns by requested frequencies.
    """
    input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)

    try:
        periods_to_resolve = [analysis.period for analysis in request.analyses]
        freqs_by_period = {analysis.period.value: analysis.frequencies for analysis in request.analyses}

        as_of_date = request.report_end_date
        resolved_periods = resolve_periods(periods_to_resolve, as_of_date, request.performance_start_date)

        if not resolved_periods:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid periods could be resolved.")

        master_start_date = min(p.start_date for p in resolved_periods)
        master_end_date = max(p.end_date for p in resolved_periods)

        engine_config = create_engine_config(request, master_start_date, master_end_date)
        engine_df = create_engine_dataframe([item.model_dump() for item in request.valuation_points])
        daily_results_df, diagnostics_data = run_calculations(engine_df, engine_config)

        results_by_period = {}
        daily_results_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
            daily_results_df[PortfolioColumns.PERF_DATE.value]
        ).dt.date

        for period in resolved_periods:
            period_slice_df = daily_results_df[
                (daily_results_df[PortfolioColumns.PERF_DATE.value] >= period.start_date)
                & (daily_results_df[PortfolioColumns.PERF_DATE.value] <= period.end_date)
            ].copy()

            if period_slice_df.empty:
                continue

            requested_frequencies_for_period = freqs_by_period.get(period.name, [])
            breakdowns_data = generate_performance_breakdowns(
                period_slice_df,
                requested_frequencies_for_period,
                request.annualization,
                request.output.include_cumulative,
                request.rounding_precision,
            )
            formatted_breakdowns = format_breakdowns_for_response(
                breakdowns_data, period_slice_df, request.output.include_timeseries
            )

            period_return_summary = _calculate_total_return_from_slice(period_slice_df, daily_results_df)
            period_result = SinglePeriodPerformanceResult(
                breakdowns=formatted_breakdowns, portfolio_return=period_return_summary
            )

            if request.reset_policy.emit and diagnostics_data.get("resets"):
                period_result.reset_events = [
                    ResetEvent(**event)
                    for event in diagnostics_data["resets"]
                    if period.start_date <= event["date"] <= period.end_date
                ]

            results_by_period[period.name] = period_result

    except InvalidEngineInputError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid Input: {e.message}")
    except EngineCalculationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Calculation Error: {e.message}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected server error occurred: {str(e)}",
        )

    meta = Meta(
        calculation_id=request.calculation_id,
        engine_version=settings.APP_VERSION,
        precision_mode=request.precision_mode,
        calendar=request.calendar,
        annualization=request.annualization,
        periods={
            "requested": [p.value for p in periods_to_resolve],
            "master_start": str(master_start_date),
            "master_end": str(master_end_date),
        },
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        report_ccy=engine_config.report_ccy,
    )
    diagnostics = Diagnostics(
        nip_days=diagnostics_data.get("nip_days", 0),
        reset_days=diagnostics_data.get("reset_days", 0),
        effective_period_start=diagnostics_data.get("effective_period_start"),
        notes=diagnostics_data.get("notes", []),
        policy=diagnostics_data.get("policy"),
        samples=diagnostics_data.get("samples"),
    )
    audit = Audit(counts={"input_rows": len(request.valuation_points), "output_rows": len(daily_results_df)})

    response_model = PerformanceResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        results_by_period=results_by_period,
        meta=meta,
        diagnostics=diagnostics,
        audit=audit,
    )

    background_tasks.add_task(
        lineage_service.capture,
        calculation_id=request.calculation_id,
        calculation_type="TWR",
        request_model=request,
        response_model=response_model,
        calculation_details={"twr_calculation_details.csv": daily_results_df},
    )

    return response_model


@router.post("/mwr", response_model=MoneyWeightedReturnResponse, summary="Calculate Money-Weighted Return")
async def calculate_mwr_endpoint(request: MoneyWeightedReturnRequest, background_tasks: BackgroundTasks):
    """Calculates the money-weighted return (MWR) for a portfolio over a given period."""
    input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)

    try:
        mwr_result = calculate_money_weighted_return(
            begin_mv=request.begin_mv,
            end_mv=request.end_mv,
            cash_flows=request.cash_flows,
            calculation_method=request.mwr_method,
            annualization=request.annualization,
            as_of=request.as_of,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during MWR calculation: {str(e)}",
        )

    meta = Meta(
        calculation_id=request.calculation_id,
        engine_version=settings.APP_VERSION,
        precision_mode=request.precision_mode,
        annualization=request.annualization,
        calendar=request.calendar,
        periods={"type": "EXPLICIT", "start": str(mwr_result.start_date), "end": str(mwr_result.end_date)},
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    diagnostics = Diagnostics(
        nip_days=0,
        reset_days=0,
        effective_period_start=mwr_result.start_date,
        notes=mwr_result.notes,
    )
    audit = Audit(counts={"cashflows": len(request.cash_flows)})

    response_payload = {
        "calculation_id": request.calculation_id,
        "portfolio_id": request.portfolio_id,
        "money_weighted_return": mwr_result.mwr,
        "mwr_annualized": mwr_result.mwr_annualized,
        "method": mwr_result.method,
        "start_date": mwr_result.start_date,
        "end_date": mwr_result.end_date,
        "notes": mwr_result.notes,
        "convergence": mwr_result.convergence,
        "meta": meta,
        "diagnostics": diagnostics,
        "audit": audit,
    }

    response_model = MoneyWeightedReturnResponse.model_validate(response_payload)

    lineage_df_data = [{"date": str(request.as_of), "type": "begin_mv", "amount": request.begin_mv}]
    lineage_df_data.extend(
        [{"date": str(cf.date), "type": "cash_flow", "amount": cf.amount} for cf in request.cash_flows]
    )
    lineage_df_data.append({"date": str(request.as_of), "type": "end_mv", "amount": request.end_mv})
    lineage_df = pd.DataFrame(lineage_df_data)

    background_tasks.add_task(
        lineage_service.capture,
        calculation_id=request.calculation_id,
        calculation_type="MWR",
        request_model=request,
        response_model=response_model,
        calculation_details={"mwr_cashflow_schedule.csv": lineage_df},
    )

    return response_model


@router.post(
    "/attribution", response_model=AttributionResponse, summary="Calculate Multi-Level Performance Attribution"
)
async def calculate_attribution_endpoint(request: AttributionRequest, background_tasks: BackgroundTasks):
    """
    Calculates multi-level, Brinson-style performance attribution, decomposing
    active return into allocation, selection, and interaction effects.
    """
    input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)

    try:
        periods_to_resolve = [analysis.period for analysis in request.analyses]
        resolved_periods = resolve_periods(periods_to_resolve, request.report_end_date, request.report_start_date)

        if not resolved_periods:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid periods could be resolved.")

        master_start_date = min(p.start_date for p in resolved_periods)
        master_end_date = max(p.end_date for p in resolved_periods)

        master_request = request.model_copy(deep=True)
        master_request.report_start_date = master_start_date
        master_request.report_end_date = master_end_date

        effects_df, lineage_data = run_attribution_calculations(master_request)

        results_by_period = {}
        for period in resolved_periods:
            period_slice_df = effects_df[
                (effects_df.index.get_level_values("date") >= pd.to_datetime(period.start_date))
                & (effects_df.index.get_level_values("date") <= pd.to_datetime(period.end_date))
            ].copy()

            if period_slice_df.empty:
                continue

            period_result, aggregation_lineage = aggregate_attribution_results(period_slice_df, request)
            if aggregation_lineage:
                lineage_data.update({f"{period.name}_{k}": v for k, v in aggregation_lineage.items()})
            results_by_period[period.name] = period_result

        meta = Meta(
            calculation_id=request.calculation_id,
            engine_version=settings.APP_VERSION,
            precision_mode=request.precision_mode,
            annualization=request.annualization,
            calendar=request.calendar,
            periods={
                "requested": [p.value for p in periods_to_resolve],
                "master_start": str(master_start_date),
                "master_end": str(master_end_date),
            },
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )

        response_model = AttributionResponse(
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            model=request.model,
            linking=request.linking,
            results_by_period=results_by_period,
            meta=meta,
        )

        background_tasks.add_task(
            lineage_service.capture,
            calculation_id=request.calculation_id,
            calculation_type="Attribution",
            request_model=request,
            response_model=response_model,
            calculation_details=lineage_data,
        )
        return response_model
    except (InvalidEngineInputError, ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except EngineCalculationError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Calculation Error: {e.message}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected server error occurred: {str(e)}",
        )
