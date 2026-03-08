# tests/conftest.py
import pytest

from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from app.workers.lineage_worker import process_pending_jobs


@pytest.fixture(scope="module")
def happy_path_payload():
    """Provides a standard, valid snake_case payload for contribution tests."""
    return {
        "portfolio_id": "CONTRIB_TEST_01",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {
                    "day": 1,
                    "perf_date": "2025-01-01",
                    "begin_mv": 1000,
                    "end_mv": 1020,
                    "bod_cf": 0,
                    "eod_cf": 0,
                    "mgmt_fees": 0,
                },
                {
                    "day": 2,
                    "perf_date": "2025-01-02",
                    "begin_mv": 1020,
                    "end_mv": 1080,
                    "bod_cf": 50,
                    "eod_cf": 0,
                    "mgmt_fees": 0,
                },
            ],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "meta": {"sector": "Technology"},
                "valuation_points": [
                    {
                        "day": 1,
                        "perf_date": "2025-01-01",
                        "begin_mv": 600,
                        "end_mv": 612,
                        "bod_cf": 0,
                        "eod_cf": 0,
                        "mgmt_fees": 0,
                    },
                    {
                        "day": 2,
                        "perf_date": "2025-01-02",
                        "begin_mv": 612,
                        "end_mv": 670,
                        "bod_cf": 50,
                        "eod_cf": 0,
                        "mgmt_fees": 0,
                    },
                ],
            }
        ],
    }


def drain_lineage_queue() -> int:
    execution_registry.create_schema()
    lineage_metadata_store.create_schema()
    return process_pending_jobs(limit=100)
