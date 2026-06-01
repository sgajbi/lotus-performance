from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.models.contribution_requests import ContributionRequest
from app.services.analytics_observation_dates import latest_observation_date
from app.services.execution_registry import UpstreamSnapshotRecord, execution_registry

logger = logging.getLogger(__name__)


def _list_upstream_snapshots_for_contribution(calculation_id: Any) -> list[UpstreamSnapshotRecord]:
    try:
        return execution_registry.list_upstream_snapshots(str(calculation_id))
    except SQLAlchemyError:
        logger.warning(
            "Contribution upstream snapshot lineage lookup failed for calculation_id=%s",
            calculation_id,
            exc_info=True,
        )
        return []


def _count_contribution_input_rows(request: ContributionRequest) -> int:
    return len(request.portfolio_data.valuation_points) + sum(
        len(position.valuation_points) for position in request.positions_data
    )


def _latest_contribution_observation_date(request: ContributionRequest):
    dates = [point.perf_date for point in request.portfolio_data.valuation_points]
    for position in request.positions_data:
        dates.extend(point.perf_date for point in position.valuation_points)
    return latest_observation_date(dates)
