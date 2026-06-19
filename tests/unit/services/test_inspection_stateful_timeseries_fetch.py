from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from app.core.config import Settings
from app.models.requests import Analysis, DailyInputData, PerformanceRequest
from app.services.inspection.stateful_timeseries_fetch import TimeseriesKind, fetch_inspection_stateful_timeseries


class _RecordingTimeseriesService:
    def __init__(self, *, status_code: int = 200, payload: dict[str, object] | None = None) -> None:
        self.status_code = status_code
        self.payload = payload or {"series": [{"value": 1.0}]}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_portfolio_timeseries(self, **kwargs: Any) -> tuple[int, dict[str, object]]:
        self.calls.append(("portfolio", kwargs))
        return self.status_code, self.payload

    async def get_position_timeseries(self, **kwargs: Any) -> tuple[int, dict[str, object]]:
        self.calls.append(("position", kwargs))
        return self.status_code, self.payload


def _performance_request() -> PerformanceRequest:
    return PerformanceRequest(
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        performance_start_date=date(2026, 4, 1),
        metric_basis="NET",
        report_end_date=date(2026, 4, 30),
        report_ccy="SGD",
        analyses=[Analysis(period="YTD", frequencies=["daily"])],
        valuation_points=[
            DailyInputData(perf_date=date(2026, 4, 1), begin_mv=1000.0, end_mv=1010.0),
            DailyInputData(perf_date=date(2026, 4, 30), begin_mv=1010.0, end_mv=1020.0),
        ],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("timeseries_kind", "expected_method"),
    [
        ("portfolio", "portfolio"),
        ("position", "position"),
    ],
)
async def test_fetch_inspection_stateful_timeseries_forwards_canonical_request_args(
    timeseries_kind: str,
    expected_method: str,
) -> None:
    service = _RecordingTimeseriesService(payload={"series": [{"perf_date": "2026-04-30"}]})
    settings = Settings()

    payload = await fetch_inspection_stateful_timeseries(
        performance_request=_performance_request(),
        portfolio_id="PB_SG_GLOBAL_BAL_001",
        settings=settings,
        service_factory=lambda *, settings: service,
        timeseries_kind=cast(TimeseriesKind, timeseries_kind),
        source_label="Portfolio timeseries",
        inspection_label="source-economics",
    )

    assert payload == {"series": [{"perf_date": "2026-04-30"}]}
    assert service.calls == [
        (
            expected_method,
            {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "as_of_date": date(2026, 4, 30),
                "start_date": date(2026, 4, 1),
                "end_date": date(2026, 4, 30),
                "reporting_currency": "SGD",
                "consumer_system": "lotus-performance-inspector",
                "calculation_id": None,
            },
        )
    ]


@pytest.mark.asyncio
async def test_fetch_inspection_stateful_timeseries_raises_source_unavailable_on_error_status() -> None:
    service = _RecordingTimeseriesService(status_code=503)

    with pytest.raises(
        RuntimeError, match="Position timeseries source unavailable for reconciliation inspection \\(503\\)"
    ):
        await fetch_inspection_stateful_timeseries(
            performance_request=_performance_request(),
            portfolio_id="PB_SG_GLOBAL_BAL_001",
            settings=Settings(),
            service_factory=lambda *, settings: service,
            timeseries_kind="position",
            source_label="Position timeseries",
            inspection_label="reconciliation",
        )
