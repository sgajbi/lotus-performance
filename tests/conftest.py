# tests/conftest.py
import pytest

from app.services.async_result_store import async_result_store
from app.services.compute_job_store import compute_job_store
from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from app.workers.compute_executor_worker import process_pending_jobs as process_pending_compute_jobs
from app.workers.lineage_worker import process_pending_jobs


@pytest.fixture(scope="module")
def happy_path_payload():
    """Provides a standard, valid snake_case payload for contribution tests."""
    return {
        "portfolio_id": "CONTRIB_TEST_01",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {
                    "perf_date": "2025-01-01",
                    "begin_mv": 1000,
                    "end_mv": 1020,
                    "bod_cf": 0,
                    "eod_cf": 0,
                    "mgmt_fees": 0,
                },
                {
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
                        "perf_date": "2025-01-01",
                        "begin_mv": 600,
                        "end_mv": 612,
                        "bod_cf": 0,
                        "eod_cf": 0,
                        "mgmt_fees": 0,
                    },
                    {
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
    bootstrap_durable_metadata_stores(
        execution_store=execution_registry,
        compute_store=compute_job_store,
        async_result_store_=async_result_store,
        lineage_store=lineage_metadata_store,
    )
    return process_pending_jobs(limit=100)


def drain_compute_queue() -> int:
    bootstrap_durable_metadata_stores(
        execution_store=execution_registry,
        compute_store=compute_job_store,
        async_result_store_=async_result_store,
    )
    return process_pending_compute_jobs(limit=100)
