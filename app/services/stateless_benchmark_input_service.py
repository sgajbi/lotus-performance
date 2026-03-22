from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import HTTPException, status

from app.models.benchmark_analytics_requests import (
    BenchmarkComponentPricePointInput,
    BenchmarkStatelessInput,
)
from app.models.benchmark_requests import BenchmarkComponentObservation


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
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
        component_points = sorted(by_component[component_id], key=lambda item: item.perf_date)
        component_dates: set[date] = set()
        for index in range(1, len(component_points)):
            previous_point = component_points[index - 1]
            current_point = component_points[index]
            previous_date = previous_point.perf_date
            current_date = current_point.perf_date
            if current_date <= previous_date:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"stateless benchmark component_price_points require non-zero prior price "
                        f"for component_id={component_id} on {previous_date}."
                    ),
                )
            component_currency = current_point.component_currency or previous_point.component_currency
            current_fx = current_point.fx_rate_to_benchmark
            previous_fx = previous_point.fx_rate_to_benchmark
            component_return_local = (current_price / previous_price) - 1.0

            if component_currency is None or component_currency == benchmark_currency:
                component_return_fx = 0.0
                normalized_previous_price = previous_price
                normalized_current_price = current_price
                resolved_currency = benchmark_currency if component_currency is None else component_currency
            else:
                if current_fx is None or previous_fx is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"stateless benchmark component_price_points require fx_rate_to_benchmark "
                            f"for cross-currency component_id={component_id} on {current_date}."
                        ),
                    )
                previous_fx_value = float(previous_fx)
                current_fx_value = float(current_fx)
                normalized_previous_price = previous_price * previous_fx_value
                normalized_current_price = current_price * current_fx_value
                component_return_fx = (current_fx_value / previous_fx_value) - 1.0
                resolved_currency = str(component_currency)

            component_return = (normalized_current_price / normalized_previous_price) - 1.0
            observations.append(
                BenchmarkComponentObservation(
                    component_id=component_id,
                    perf_date=current_date,
                    weight_bop=float(current_point.weight_bop),
                    component_currency=resolved_currency,
                    component_return=component_return,
                    component_return_local=component_return_local,
                    component_return_fx=component_return_fx,
                )
            )
            component_dates.add(current_date)

        if expected_component_dates is None:
            expected_component_dates = component_dates
        elif component_dates != expected_component_dates:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "stateless benchmark component_price_points must yield the same derived return-date "
                    f"set for every component; component_id={component_id} does not match peer coverage."
                ),
            )

    if not observations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "stateless benchmark component_price_points did not yield any benchmark return observations; "
                "at least two price points per component are required."
            ),
        )
    return observations
