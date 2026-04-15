from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.inspection_requests import TWRInspectionRequest


def test_twr_calculation_inspection_rejects_embedded_request_payload():
    with pytest.raises(ValidationError, match="requires subject_calculation_id and does not accept request payload"):
        TWRInspectionRequest(
            subject_type="twr_calculation",
            subject_calculation_id=uuid4(),
            request=_twr_request_payload(),
        )


def test_twr_request_inspection_rejects_subject_calculation_id():
    with pytest.raises(ValidationError, match="requires request payload and does not accept subject_calculation_id"):
        TWRInspectionRequest(
            subject_type="twr_request",
            subject_calculation_id=uuid4(),
            request=_twr_request_payload(),
        )


def _twr_request_payload() -> dict:
    return {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "performance_start_date": "2026-01-01",
        "metric_basis": "NET",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2026-01-02", "begin_mv": 1000.0, "end_mv": 1001.0}],
    }
