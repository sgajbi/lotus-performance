from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, Sequence

import pandas as pd


@dataclass(frozen=True)
class BenchmarkEngineResult:
    daily_returns_df: pd.DataFrame
    component_contributions_df: pd.DataFrame
    effective_period_start: date
    max_weight_sum_deviation: float
    notes: list[str]


class BenchmarkComponentObservationLike(Protocol):
    perf_date: date
    component_id: str
    component_currency: str
    weight_bop: Any
    component_return: Any
    component_return_local: Any | None
    component_return_fx: Any | None


class BenchmarkReturnPointLike(Protocol):
    perf_date: date
    benchmark_return: Any


def _component_contributions_dataframe(
    component_observations: Sequence[BenchmarkComponentObservationLike],
    *,
    has_any_local: bool,
) -> pd.DataFrame:
    records = [_component_contribution_record(observation) for observation in component_observations]
    contributions_df = pd.DataFrame(records)
    if contributions_df.duplicated(subset=["date", "component_id"]).any():
        raise ValueError("Duplicate component observation detected for the same date/component_id")

    contributions_df = contributions_df.sort_values(["date", "component_id"]).reset_index(drop=True)
    contributions_df["contribution"] = contributions_df["weight_bop"] * contributions_df["component_return"]
    if has_any_local:
        contributions_df["local_contribution"] = (
            contributions_df["weight_bop"] * contributions_df["component_return_local"]
        )
        contributions_df["fx_contribution"] = contributions_df["weight_bop"] * contributions_df["component_return_fx"]
    return contributions_df


def _component_contribution_record(observation: BenchmarkComponentObservationLike) -> dict[str, Any]:
    return {
        "date": observation.perf_date,
        "component_id": observation.component_id,
        "component_currency": observation.component_currency,
        "weight_bop": Decimal(str(observation.weight_bop)),
        "component_return": Decimal(str(observation.component_return)),
        "component_return_local": (
            Decimal(str(observation.component_return_local)) if observation.component_return_local is not None else None
        ),
        "component_return_fx": (
            Decimal(str(observation.component_return_fx)) if observation.component_return_fx is not None else None
        ),
    }


def _aggregate_benchmark_returns(
    contributions_df: pd.DataFrame,
    *,
    has_any_local: bool,
) -> pd.DataFrame:
    grouped = contributions_df.groupby("date", sort=True).agg(
        benchmark_return=("contribution", "sum"),
        weight_sum=("weight_bop", "sum"),
    )
    if has_any_local:
        grouped["weighted_local_return_sum"] = contributions_df.groupby("date", sort=True)["local_contribution"].sum()
        grouped["weighted_fx_return_sum"] = contributions_df.groupby("date", sort=True)["fx_contribution"].sum()
    grouped = grouped.reset_index()

    if has_any_local:
        grouped["benchmark_return_local"] = grouped.apply(
            lambda row: (
                Decimal("0") if row["weight_sum"] == 0 else row["weighted_local_return_sum"] / row["weight_sum"]
            ),
            axis=1,
        )
        grouped["benchmark_return_fx"] = grouped.apply(
            lambda row: Decimal("0") if row["weight_sum"] == 0 else row["weighted_fx_return_sum"] / row["weight_sum"],
            axis=1,
        )
    return grouped


def _cumulative_benchmark_returns(grouped: pd.DataFrame) -> list[Decimal]:
    cumulative_returns: list[Decimal] = []
    running = Decimal("1")
    for benchmark_return in grouped["benchmark_return"]:
        running *= Decimal("1") + benchmark_return
        cumulative_returns.append(running - Decimal("1"))
    return cumulative_returns


def _benchmark_weight_diagnostics(grouped: pd.DataFrame) -> tuple[Decimal, list[str]]:
    max_weight_sum_deviation_decimal = max(
        (abs(Decimal("1") - weight_sum) for weight_sum in grouped["weight_sum"]),
        default=Decimal("0"),
    )
    notes: list[str] = []
    if max_weight_sum_deviation_decimal != Decimal("0"):
        notes.append("Benchmark component weights do not sum exactly to 1.0 on every date.")
    return max_weight_sum_deviation_decimal, notes


def calculate_benchmark_returns(
    component_observations: Sequence[BenchmarkComponentObservationLike],
) -> BenchmarkEngineResult:
    if not component_observations:
        raise ValueError("component_observations must not be empty")

    has_any_local = _uses_local_fx_component_returns(component_observations)
    contributions_df = _component_contributions_dataframe(
        component_observations,
        has_any_local=has_any_local,
    )
    grouped = _aggregate_benchmark_returns(contributions_df, has_any_local=has_any_local)
    grouped["cumulative_return"] = _cumulative_benchmark_returns(grouped)
    max_weight_sum_deviation_decimal, notes = _benchmark_weight_diagnostics(grouped)

    return BenchmarkEngineResult(
        daily_returns_df=grouped,
        component_contributions_df=contributions_df,
        effective_period_start=min(observation.perf_date for observation in component_observations),
        max_weight_sum_deviation=float(max_weight_sum_deviation_decimal),
        notes=notes,
    )


def _uses_local_fx_component_returns(
    component_observations: Sequence[BenchmarkComponentObservationLike],
) -> bool:
    has_any_local, has_any_fx = _component_local_fx_presence(component_observations)
    if has_any_local != has_any_fx:
        raise ValueError("component_return_local and component_return_fx must be supplied together")
    if has_any_local and _has_incomplete_local_fx_component_return(component_observations):
        raise ValueError("component_return_local and component_return_fx must be populated for every observation")
    return has_any_local


def _component_local_fx_presence(
    component_observations: Sequence[BenchmarkComponentObservationLike],
) -> tuple[bool, bool]:
    return (
        any(observation.component_return_local is not None for observation in component_observations),
        any(observation.component_return_fx is not None for observation in component_observations),
    )


def _has_incomplete_local_fx_component_return(
    component_observations: Sequence[BenchmarkComponentObservationLike],
) -> bool:
    return any(
        observation.component_return_local is None or observation.component_return_fx is None
        for observation in component_observations
    )


def benchmark_return_points_to_dataframe(
    benchmark_return_points: Sequence[BenchmarkReturnPointLike],
) -> pd.DataFrame:
    if not benchmark_return_points:
        raise ValueError("benchmark_return_points must not be empty")
    records = [
        {
            "date": point.perf_date,
            "benchmark_return": Decimal(str(point.benchmark_return)),
            "benchmark_return_local": None,
            "benchmark_return_fx": None,
        }
        for point in benchmark_return_points
    ]
    returns_df = pd.DataFrame(records)
    if returns_df.duplicated(subset=["date"]).any():
        raise ValueError("Duplicate benchmark_return_points detected for the same date")
    returns_df = returns_df.sort_values("date").reset_index(drop=True)

    cumulative_returns: list[Decimal] = []
    running = Decimal("1")
    for benchmark_return in returns_df["benchmark_return"]:
        running *= Decimal("1") + benchmark_return
        cumulative_returns.append(running - Decimal("1"))
    returns_df["cumulative_return"] = cumulative_returns
    returns_df["weight_sum"] = Decimal("1")
    return returns_df
