# engine/periods.py
import pandas as pd

from common.enums import PeriodType
from engine.config import EngineConfig

_CALENDAR_PERIOD_FREQUENCIES = {
    PeriodType.YTD: "Y",
    PeriodType.MTD: "M",
    PeriodType.QTD: "Q",
}

_FIXED_YEAR_PERIODS = {
    PeriodType.ONE_YEAR: 1,
    PeriodType.THREE_YEARS: 3,
    PeriodType.FIVE_YEARS: 5,
}


def get_effective_period_start_dates(perf_dates_dt: pd.Series, config: EngineConfig) -> pd.Series:
    """
    Vectorized calculation of the effective period start date for each row.
    Returns a Series with dtype=datetime64[ns].
    """
    if config.period_type in _CALENDAR_PERIOD_FREQUENCIES:
        return _calendar_effective_period_start_dates(perf_dates_dt, config)
    if config.period_type == PeriodType.EXPLICIT:
        return _constant_period_start_dates(perf_dates_dt, _explicit_period_start_date(config))
    if config.period_type in _FIXED_YEAR_PERIODS:
        return _constant_period_start_dates(perf_dates_dt, _fixed_year_period_start_date(config))
    return _constant_period_start_dates(perf_dates_dt, config.performance_start_date)


def _calendar_effective_period_start_dates(perf_dates_dt: pd.Series, config: EngineConfig) -> pd.Series:
    frequency = _CALENDAR_PERIOD_FREQUENCIES[config.period_type]
    effective_starts = perf_dates_dt.dt.to_period(frequency).dt.start_time

    perf_start_dt = pd.to_datetime(config.performance_start_date)

    return effective_starts.where(effective_starts >= perf_start_dt, perf_start_dt).astype("datetime64[ns]")


def _explicit_period_start_date(config: EngineConfig):
    return max(
        config.performance_start_date,
        config.report_start_date or config.performance_start_date,
    )


def _fixed_year_period_start_date(config: EngineConfig) -> pd.Timestamp:
    years = _FIXED_YEAR_PERIODS[config.period_type]
    return pd.to_datetime(config.report_end_date) - pd.DateOffset(years=years) + pd.Timedelta(days=1)


def _constant_period_start_dates(perf_dates_dt: pd.Series, start_date) -> pd.Series:
    return pd.Series(pd.to_datetime(start_date), index=perf_dates_dt.index, name=perf_dates_dt.name).astype(
        "datetime64[ns]"
    )
