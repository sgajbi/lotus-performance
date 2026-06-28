from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.endpoints import benchmark_exposure_context as benchmark_exposure_context_endpoint
from app.models.benchmark_exposure_context import BenchmarkExposureContextRequest


def _request() -> BenchmarkExposureContextRequest:
    return BenchmarkExposureContextRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "as_of_date": "2026-03-31",
            "window": {"start_date": "2026-01-01", "end_date": "2026-03-31"},
            "frequency": "DAILY",
            "reporting_currency": "USD",
            "grouping_dimensions": ["SECTOR"],
        }
    )


@pytest.mark.asyncio
async def test_benchmark_exposure_context_endpoint_delegates_to_workflow_service(mocker) -> None:
    request = _request()
    expected_response = mocker.Mock(rows=[{"group_key": "SECTOR_TECH"}])

    workflow = mocker.patch(
        "app.api.endpoints.benchmark_exposure_context.calculate_benchmark_exposure_context_response",
        return_value=expected_response,
    )

    response = await benchmark_exposure_context_endpoint.get_benchmark_exposure_context(request)

    assert response is expected_response
    workflow.assert_awaited_once_with(request)
