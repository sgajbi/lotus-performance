from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException

from app.models.benchmark_analytics_requests import (
    BenchmarkComponentPricePointInput,
    BenchmarkStatelessInput,
)
from app.models.benchmark_requests import BenchmarkComponentObservation
from core.errors import HTTP_422_UNPROCESSABLE

_RatioNumber = float


@dataclass(frozen=True)
class _PricePointReturnComponents:
    currency: str
    total: float
    local: float
    fx: float


def normalize_stateless_component_observations(
    *,
    benchmark_currency: str,
    stateless_input: BenchmarkStatelessInput,
) -> list[dict[str, object]]:
    if stateless_input.component_observations:
        return [observation.model_dump(mode="python") for observation in stateless_input.component_observations]
    if stateless_input.component_price_points:
        return [
            observation.model_dump(mode="python")
            for observation in _build_component_observations_from_price_points(
                benchmark_currency=benchmark_currency,
                stateless_input=stateless_input,
            )
        ]
    raise HTTPException(
        status_code=HTTP_422_UNPROCESSABLE,
        detail=(
            "stateless benchmark calculated mode requires either component_observations or component_price_points."
        ),
    )


def _build_component_observations_from_price_points(
    *,
    benchmark_currency: str,
    stateless_input: BenchmarkStatelessInput,
) -> list[BenchmarkComponentObservation]:
    by_component: dict[str, list[BenchmarkComponentPricePointInput]] = defaultdict(list)
    for price_point in stateless_input.component_price_points:
        by_component[price_point.component_id].append(price_point)

    observations: list[BenchmarkComponentObservation] = []
    expected_component_dates: set[date] | None = None
    for component_id in sorted(by_component):
        component_observations, component_dates = _component_observations_from_price_points(
            benchmark_currency=benchmark_currency,
            component_id=component_id,
            price_points=by_component[component_id],
        )
        observations.extend(component_observations)

        if expected_component_dates is None:
            expected_component_dates = component_dates
        elif component_dates != expected_component_dates:
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail=(
                    "stateless benchmark component_price_points must yield the same derived return-date "
                    f"set for every component; component_id={component_id} does not match peer coverage."
                ),
            )

    if not observations:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=(
                "stateless benchmark component_price_points did not yield any benchmark return observations; "
                "at least two price points per component are required."
            ),
        )
    return observations


def _component_observations_from_price_points(
    *,
    benchmark_currency: str,
    component_id: str,
    price_points: list[BenchmarkComponentPricePointInput],
) -> tuple[list[BenchmarkComponentObservation], set[date]]:
    component_observations: list[BenchmarkComponentObservation] = []
    component_dates: set[date] = set()
    component_points = sorted(price_points, key=lambda item: item.perf_date)
    for index in range(1, len(component_points)):
        observation = _build_price_point_observation(
            component_id=component_id,
            benchmark_currency=benchmark_currency,
            previous_point=component_points[index - 1],
            current_point=component_points[index],
        )
        component_observations.append(observation)
        component_dates.add(observation.perf_date)
    return component_observations, component_dates


def _build_price_point_observation(
    *,
    component_id: str,
    benchmark_currency: str,
    previous_point: BenchmarkComponentPricePointInput,
    current_point: BenchmarkComponentPricePointInput,
) -> BenchmarkComponentObservation:
    previous_date = previous_point.perf_date
    current_date = current_point.perf_date
    if current_date <= previous_date:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=(
                "stateless benchmark component_price_points require strictly increasing unique dates "
                f"per component; component_id={component_id} contains duplicate or non-monotonic "
                f"date {current_date}."
            ),
        )
    previous_price = float(previous_point.index_price)
    current_price = float(current_point.index_price)
    if previous_price == 0:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=(
                f"stateless benchmark component_price_points require non-zero prior price "
                f"for component_id={component_id} on {previous_date}."
            ),
        )
    return_components = _price_point_return_components(
        component_id=component_id,
        benchmark_currency=benchmark_currency,
        previous_level=previous_price,
        current_level=current_price,
        previous_point=previous_point,
        current_point=current_point,
    )
    return BenchmarkComponentObservation(
        component_id=component_id,
        perf_date=current_date,
        weight_bop=float(current_point.weight_bop),
        component_currency=return_components.currency,
        component_return=return_components.total,
        component_return_local=return_components.local,
        component_return_fx=return_components.fx,
    )


def _price_point_return_components(
    *,
    component_id: str,
    benchmark_currency: str,
    previous_level: float,
    current_level: float,
    previous_point: BenchmarkComponentPricePointInput,
    current_point: BenchmarkComponentPricePointInput,
) -> _PricePointReturnComponents:
    component_currency = current_point.component_currency or previous_point.component_currency
    component_return_local = (current_level / previous_level) - 1.0
    if component_currency is None or component_currency == benchmark_currency:
        return _PricePointReturnComponents(
            currency=benchmark_currency if component_currency is None else component_currency,
            total=component_return_local,
            local=component_return_local,
            fx=0.0,
        )

    return _cross_currency_price_point_return_components(
        component_id=component_id,
        component_currency=str(component_currency),
        local_return=component_return_local,
        previous_level=previous_level,
        current_level=current_level,
        previous_point=previous_point,
        current_point=current_point,
    )


def _cross_currency_price_point_return_components(
    *,
    component_id: str,
    component_currency: str,
    local_return: _RatioNumber,
    previous_level: float,
    current_level: float,
    previous_point: BenchmarkComponentPricePointInput,
    current_point: BenchmarkComponentPricePointInput,
) -> _PricePointReturnComponents:
    current_fx = current_point.fx_rate_to_benchmark
    previous_fx = previous_point.fx_rate_to_benchmark
    if current_fx is None or previous_fx is None:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=(
                f"stateless benchmark component_price_points require fx_rate_to_benchmark "
                f"for cross-currency component_id={component_id} on {current_point.perf_date}."
            ),
        )
    previous_fx_value = float(previous_fx)
    current_fx_value = float(current_fx)
    normalized_previous_price = previous_level * previous_fx_value
    normalized_current_price = current_level * current_fx_value
    return _PricePointReturnComponents(
        currency=component_currency,
        total=(normalized_current_price / normalized_previous_price) - 1.0,
        local=local_return,
        fx=(current_fx_value / previous_fx_value) - 1.0,
    )
