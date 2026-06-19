from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from fastapi import HTTPException, status

from app.services.stateful_input_service import StatefulInputService
from app.services.stateful_upstream_errors import raise_for_stateful_source_unavailable
from core.errors import HTTP_422_UNPROCESSABLE


@dataclass(frozen=True)
class ResolvedBenchmarkIdentity:
    benchmark_id: str
    source_details: dict[str, int]


def _resolved_assignment_identity(
    *,
    portfolio_id: str,
    assignment_status: int,
    assignment_payload: dict[str, object],
) -> ResolvedBenchmarkIdentity:
    _raise_for_unusable_assignment_status(
        portfolio_id=portfolio_id,
        assignment_status=assignment_status,
    )
    return ResolvedBenchmarkIdentity(
        benchmark_id=_benchmark_id_from_assignment_payload(assignment_payload),
        source_details={"resolved_benchmark_assignment": 1},
    )


def _raise_for_unusable_assignment_status(
    *,
    portfolio_id: str,
    assignment_status: int,
) -> None:
    if assignment_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No benchmark assignment found for portfolio_id={portfolio_id}.",
        )
    if assignment_status >= status.HTTP_400_BAD_REQUEST:
        raise_for_stateful_source_unavailable(
            source_label="benchmark assignment",
            upstream_status=assignment_status,
        )


def _benchmark_id_from_assignment_payload(assignment_payload: dict[str, object]) -> str:
    benchmark_id_raw = assignment_payload.get("benchmark_id")
    if not isinstance(benchmark_id_raw, str) or not benchmark_id_raw:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="benchmark assignment payload missing benchmark_id.",
        )
    return benchmark_id_raw


async def resolve_benchmark_identity(
    *,
    stateful_input_service: StatefulInputService,
    portfolio_id: str,
    as_of_date: date,
    reporting_currency: str | None,
    calculation_id: UUID,
    benchmark_id: str | None,
) -> ResolvedBenchmarkIdentity:
    if benchmark_id is not None:
        return ResolvedBenchmarkIdentity(benchmark_id=benchmark_id, source_details={})

    assignment_status, assignment_payload = await stateful_input_service.get_benchmark_assignment(
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        reporting_currency=reporting_currency,
        calculation_id=calculation_id,
    )
    return _resolved_assignment_identity(
        portfolio_id=portfolio_id,
        assignment_status=assignment_status,
        assignment_payload=assignment_payload,
    )
