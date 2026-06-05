# engine/compute.py
import logging
from decimal import Decimal
from typing import Tuple

import numpy as np
import pandas as pd

from engine.config import EngineConfig, PrecisionMode
from engine.diagnostics import EngineDiagnostics, EngineResetEvent, MethodologyShadowSample
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from engine.periods import get_effective_period_start_dates
from engine.policies import _flag_outliers, apply_robustness_policies
from engine.ror import calculate_cumulative_ror, calculate_daily_ror
from engine.rules import calculate_initial_sign, calculate_nip, calculate_nip_variants, calculate_sign
from engine.schema import PortfolioColumns

logger = logging.getLogger(__name__)


def run_calculations(df: pd.DataFrame, config: EngineConfig) -> Tuple[pd.DataFrame, EngineDiagnostics]:
    """
    Orchestrates the full portfolio performance calculation pipeline using
    a fully vectorized approach.
    Returns a DataFrame and a diagnostics dictionary.
    """
    try:
        if not isinstance(df, pd.DataFrame):
            raise InvalidEngineInputError("Input must be a pandas DataFrame.")

        if df.empty:
            return pd.DataFrame(), EngineDiagnostics()

        working_df = df.copy(deep=True)
        _prepare_dataframe(working_df, config)

        working_df, policy_diagnostics = apply_robustness_policies(working_df, config.data_policy)
        _attach_effective_period_and_daily_returns(working_df, config)
        _apply_data_policy_outlier_flags(working_df, config, policy_diagnostics)

        working_df[PortfolioColumns.SIGN.value] = calculate_sign(working_df)
        nip_v1, nip_v2 = calculate_nip_variants(working_df)
        working_df["nip_rule_v1_shadow"] = nip_v1
        working_df["nip_rule_v2_shadow"] = nip_v2
        working_df["initial_sign_shadow"] = calculate_initial_sign(working_df)
        working_df[PortfolioColumns.NIP.value] = calculate_nip(working_df, config)

        calculate_cumulative_ror(working_df, config)

        working_df[PortfolioColumns.LONG_SHORT.value] = np.select(
            [working_df[PortfolioColumns.SIGN.value] == -1, working_df[PortfolioColumns.SIGN.value] == 1],
            ["S", "L"],
            default="N",
        )

        reset_events = _build_reset_events(working_df)

        final_df = _filter_results_to_reporting_period(working_df, config)

        if config.precision_mode != PrecisionMode.DECIMAL_STRICT:
            _round_float_columns(final_df, config.rounding_precision)

        diagnostics = _build_engine_diagnostics(
            working_df=working_df,
            final_df=final_df,
            policy_diagnostics=policy_diagnostics,
            reset_events=reset_events,
        )

    except InvalidEngineInputError:
        raise
    except Exception as e:
        logger.exception("An unexpected error occurred during engine calculations.")
        raise EngineCalculationError(f"Engine calculation failed unexpectedly: {e}")

    logger.info("Performance engine calculation complete.")
    return final_df, diagnostics


def _attach_effective_period_and_daily_returns(working_df: pd.DataFrame, config: EngineConfig) -> None:
    working_df[PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value] = get_effective_period_start_dates(
        working_df[PortfolioColumns.PERF_DATE.value], config
    )

    ror_df = calculate_daily_ror(working_df, config.metric_basis, config)
    for col in ror_df.columns:
        working_df[col] = ror_df[col]


def _apply_data_policy_outlier_flags(
    working_df: pd.DataFrame,
    config: EngineConfig,
    policy_diagnostics: EngineDiagnostics,
) -> None:
    if not config.data_policy:
        return

    ignored_dates = {ignored_date for item in config.data_policy.ignore_days or [] for ignored_date in item.dates}
    _flag_outliers(working_df, config.data_policy, policy_diagnostics, ignored_dates=ignored_dates)


def _build_reset_events(working_df: pd.DataFrame) -> list[EngineResetEvent]:
    working_df[PortfolioColumns.PERF_RESET.value] = working_df[PortfolioColumns.PERF_RESET.value].astype(int)
    reset_events: list[EngineResetEvent] = []
    reset_rows = working_df[working_df[PortfolioColumns.PERF_RESET.value] == 1]
    for _, row in reset_rows.iterrows():
        reason_codes = _reset_reason_codes(row)
        reset_events.append(
            EngineResetEvent(
                date=row[PortfolioColumns.PERF_DATE.value].date(),
                reason=",".join(reason_codes) or "UNKNOWN",
                impacted_rows=1,
            )
        )
    return reset_events


def _build_engine_diagnostics(
    *,
    working_df: pd.DataFrame,
    final_df: pd.DataFrame,
    policy_diagnostics: EngineDiagnostics,
    reset_events: list[EngineResetEvent],
) -> EngineDiagnostics:
    nip_rule_delta_days = _calculate_nip_rule_delta_days(final_df)
    nip_days_since_last_reset, valid_days_since_last_reset = _calculate_reset_relative_day_counts(final_df)
    (
        nctrl4_reset_days,
        nctrl4_exclusive_reset_days,
        account_reset_shadow_days,
        sod_reset_shadow_days,
        shadow_reset_overlap_days,
        shadow_only_candidate_reset_days,
        active_reset_with_shadow_days,
    ) = _calculate_reset_reason_characterization_counts(final_df)
    candidate_canonical_reset_days, reset_delta_days = _calculate_reset_delta_counts(final_df)

    diagnostics = EngineDiagnostics(
        nip_days=int(final_df[PortfolioColumns.NIP.value].sum()),
        nip_rule_delta_days=nip_rule_delta_days,
        reset_days=int(final_df[PortfolioColumns.PERF_RESET.value].sum()),
        nctrl4_reset_days=nctrl4_reset_days,
        nctrl4_exclusive_reset_days=nctrl4_exclusive_reset_days,
        account_reset_shadow_days=account_reset_shadow_days,
        sod_reset_shadow_days=sod_reset_shadow_days,
        shadow_reset_overlap_days=shadow_reset_overlap_days,
        shadow_only_candidate_reset_days=shadow_only_candidate_reset_days,
        active_reset_with_shadow_days=active_reset_with_shadow_days,
        candidate_canonical_reset_days=candidate_canonical_reset_days,
        reset_delta_days=reset_delta_days,
        nip_days_since_last_reset=nip_days_since_last_reset,
        valid_days_since_last_reset=valid_days_since_last_reset,
        effective_period_start=working_df[PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value].min().date(),
        notes=list(policy_diagnostics.notes),
        resets=reset_events,
        policy=policy_diagnostics.policy,
        samples=policy_diagnostics.samples,
    )
    diagnostics.samples.methodology_shadows.extend(_build_methodology_shadow_samples(final_df))
    return diagnostics


def _prepare_dataframe(df: pd.DataFrame, config: EngineConfig):
    """Initializes and prepares the DataFrame for calculation, handling precision mode."""
    numeric_cols = [
        PortfolioColumns.DAY.value,
        PortfolioColumns.BEGIN_MV.value,
        PortfolioColumns.BOD_CF.value,
        PortfolioColumns.EOD_CF.value,
        PortfolioColumns.MGMT_FEES.value,
        PortfolioColumns.END_MV.value,
        PortfolioColumns.ACCOUNT_PERFORMANCE_RESET.value,
    ]

    if config.precision_mode == PrecisionMode.DECIMAL_STRICT:
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: Decimal(str(x)) if pd.notna(x) else Decimal(0))
    else:
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(df[PortfolioColumns.PERF_DATE.value], errors="coerce")
    if df[PortfolioColumns.PERF_DATE.value].isnull().any():
        raise InvalidEngineInputError("One or more 'perf_date' values are invalid or missing.")

    for col in PortfolioColumns:
        if col.value not in df.columns and col.value not in [
            PortfolioColumns.LONG_SHORT.value,
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value,
        ]:
            df[col.value] = Decimal(0) if config.precision_mode == PrecisionMode.DECIMAL_STRICT else 0.0
    df[PortfolioColumns.PERF_RESET.value] = 0
    df[PortfolioColumns.LONG_SHORT.value] = ""


def _reset_reason_codes(row: pd.Series) -> list[str]:
    """Returns the active reset reasons that currently drive engine compounding."""
    reason_codes: list[str] = []
    if row.get(PortfolioColumns.NCTRL_1.value, 0):
        reason_codes.append("NCTRL_1")
    if row.get(PortfolioColumns.NCTRL_2.value, 0):
        reason_codes.append("NCTRL_2")
    if row.get(PortfolioColumns.NCTRL_3.value, 0):
        reason_codes.append("NCTRL_3")
    if row.get(PortfolioColumns.NCTRL_4.value, 0):
        reason_codes.append("NCTRL_4")
    return reason_codes


def _candidate_canonical_reset_reason_codes(row: pd.Series) -> list[str]:
    """Returns the reset reasons that would participate in the candidate canonical reset model."""
    reason_codes = _reset_reason_codes(row)
    if row.get(PortfolioColumns.ACCOUNT_RESET.value, 0):
        reason_codes.append("ACCOUNT_RESET")
    if row.get(PortfolioColumns.SOD_RESET.value, 0):
        reason_codes.append("SOD_RESET")
    return reason_codes


def _calculate_reset_relative_day_counts(final_df: pd.DataFrame) -> tuple[int, int]:
    """Counts NIP and valid days from the last reset boundary within the reporting slice."""
    if final_df.empty:
        return 0, 0

    reset_mask = final_df[PortfolioColumns.PERF_RESET.value] == 1
    if reset_mask.any():
        last_reset_index = final_df[reset_mask].index[-1]
        relevant_df = final_df.loc[last_reset_index:]
    else:
        relevant_df = final_df

    nip_days_since_last_reset = int(relevant_df[PortfolioColumns.NIP.value].sum())
    valid_days_since_last_reset = int(len(relevant_df) - nip_days_since_last_reset)
    return nip_days_since_last_reset, valid_days_since_last_reset


def _calculate_nip_rule_delta_days(final_df: pd.DataFrame) -> int:
    """Counts reporting-slice days where the two supported NIP rules disagree."""
    if final_df.empty:
        return 0

    return int((final_df["nip_rule_v1_shadow"] != final_df["nip_rule_v2_shadow"]).sum())


def _calculate_reset_delta_counts(final_df: pd.DataFrame) -> tuple[int, int]:
    """Counts reset days under the candidate canonical model and its delta from active resets."""
    if final_df.empty:
        return 0, 0

    active_reset_mask = final_df[PortfolioColumns.PERF_RESET.value] == 1
    candidate_canonical_reset_mask = (
        active_reset_mask
        | (final_df[PortfolioColumns.SOD_RESET.value] == 1)
        | (final_df[PortfolioColumns.ACCOUNT_RESET.value] == 1)
    )
    reset_delta_mask = candidate_canonical_reset_mask != active_reset_mask

    return int(candidate_canonical_reset_mask.sum()), int(reset_delta_mask.sum())


def _calculate_reset_reason_characterization_counts(final_df: pd.DataFrame) -> tuple[int, int, int, int, int, int, int]:
    """Summarizes how active and shadow reset reasons appear within the reporting slice."""
    if final_df.empty:
        return 0, 0, 0, 0, 0, 0, 0

    active_reset_mask = final_df[PortfolioColumns.PERF_RESET.value] == 1
    nctrl4_mask = final_df[PortfolioColumns.NCTRL_4.value] == 1
    account_reset_mask = final_df[PortfolioColumns.ACCOUNT_RESET.value] == 1
    sod_reset_mask = final_df[PortfolioColumns.SOD_RESET.value] == 1
    shadow_overlap_mask = account_reset_mask & sod_reset_mask
    any_shadow_mask = account_reset_mask | sod_reset_mask
    nctrl4_exclusive_mask = nctrl4_mask & ~any_shadow_mask
    shadow_only_candidate_reset_mask = any_shadow_mask & ~active_reset_mask
    active_reset_with_shadow_mask = active_reset_mask & any_shadow_mask

    return (
        int(nctrl4_mask.sum()),
        int(nctrl4_exclusive_mask.sum()),
        int(account_reset_mask.sum()),
        int(sod_reset_mask.sum()),
        int(shadow_overlap_mask.sum()),
        int(shadow_only_candidate_reset_mask.sum()),
        int(active_reset_with_shadow_mask.sum()),
    )


def _build_methodology_shadow_samples(final_df: pd.DataFrame) -> list[MethodologyShadowSample]:
    """Builds compact characterization samples for reset, NIP, and sign semantics."""
    if final_df.empty:
        return []

    samples: list[MethodologyShadowSample] = []
    previous_sign = final_df[PortfolioColumns.SIGN.value].shift(1, fill_value=0)

    reset_mask = final_df[PortfolioColumns.PERF_RESET.value] == 1
    if reset_mask.any():
        reset_dates = final_df.loc[reset_mask, PortfolioColumns.PERF_DATE.value].tolist()
        last_reset_date = max(reset_dates)
        reset_relative_mask = final_df[PortfolioColumns.PERF_DATE.value] >= last_reset_date
    else:
        reset_relative_mask = pd.Series([True] * len(final_df), index=final_df.index)

    interesting_mask = (
        (final_df["nip_rule_v1_shadow"] != final_df["nip_rule_v2_shadow"])
        | (final_df[PortfolioColumns.PERF_RESET.value] == 1)
        | (final_df[PortfolioColumns.SOD_RESET.value] == 1)
        | (final_df[PortfolioColumns.ACCOUNT_RESET.value] == 1)
        | (
            (
                (final_df[PortfolioColumns.PERF_RESET.value] == 1)
                | (final_df[PortfolioColumns.SOD_RESET.value] == 1)
                | (final_df[PortfolioColumns.ACCOUNT_RESET.value] == 1)
            )
            != (final_df[PortfolioColumns.PERF_RESET.value] == 1)
        )
        | (previous_sign == 0)
        | (~reset_relative_mask)
    )

    for idx, row in final_df[interesting_mask].iterrows():
        active_reset_reason_codes = _reset_reason_codes(row)
        candidate_canonical_reset_reason_codes = _candidate_canonical_reset_reason_codes(row)
        samples.append(
            MethodologyShadowSample(
                date=row[PortfolioColumns.PERF_DATE.value].isoformat(),
                active_nip=int(row[PortfolioColumns.NIP.value]),
                nip_rule_v1=int(row["nip_rule_v1_shadow"]),
                nip_rule_v2=int(row["nip_rule_v2_shadow"]),
                active_perf_reset=int(row[PortfolioColumns.PERF_RESET.value]),
                candidate_canonical_perf_reset=int(bool(candidate_canonical_reset_reason_codes)),
                sod_reset_shadow=int(row[PortfolioColumns.SOD_RESET.value]),
                account_reset_shadow=int(row.get(PortfolioColumns.ACCOUNT_RESET.value, 0)),
                previous_sign_zero=int(previous_sign.loc[idx] == 0),
                initial_sign=int(row["initial_sign_shadow"]),
                final_sign=int(row[PortfolioColumns.SIGN.value]),
                active_reset_reason_codes=active_reset_reason_codes,
                candidate_canonical_reset_reason_codes=candidate_canonical_reset_reason_codes,
            )
        )

    return samples


def _filter_results_to_reporting_period(df: pd.DataFrame, config: EngineConfig) -> pd.DataFrame:
    """Filters the DataFrame to only include dates within the reporting period."""
    effective_report_start = pd.to_datetime(config.report_start_date or config.performance_start_date)
    report_end_date = pd.to_datetime(config.report_end_date)

    mask = (df[PortfolioColumns.PERF_DATE.value] >= effective_report_start) & (
        df[PortfolioColumns.PERF_DATE.value] <= report_end_date
    )

    final_df = df[mask].copy()
    final_df[PortfolioColumns.PERF_DATE.value] = final_df[PortfolioColumns.PERF_DATE.value].dt.date

    return final_df


def _round_float_columns(df: pd.DataFrame, precision: int):
    """Rounds float columns to a specified precision to ensure consistency."""
    float_cols = df.select_dtypes(include=["float64"]).columns
    df[float_cols] = df[float_cols].round(precision)
