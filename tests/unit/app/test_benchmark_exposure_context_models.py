from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.benchmark_exposure_context import BenchmarkExposureContextRequest, BenchmarkExposureWindow


def test_benchmark_exposure_window_rejects_inverted_dates() -> None:
    with pytest.raises(ValueError, match="window.start_date cannot be after window.end_date"):
        BenchmarkExposureWindow.model_validate({"start_date": "2026-03-31", "end_date": "2026-01-01"})


def test_benchmark_exposure_context_requires_at_least_one_grouping_dimension() -> None:
    with pytest.raises(ValueError, match="grouping_dimensions must contain at least one value"):
        BenchmarkExposureContextRequest.model_validate(
            {
                "calculation_id": str(uuid4()),
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "as_of_date": "2026-03-31",
                "window": {"start_date": "2026-01-01", "end_date": "2026-03-31"},
                "grouping_dimensions": [],
            }
        )
