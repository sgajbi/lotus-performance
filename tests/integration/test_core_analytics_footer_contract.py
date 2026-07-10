from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _assert_shared_footer(body: dict) -> None:
    assert isinstance(body["meta"], dict)
    assert body["meta"]["calculation_id"]
    assert body["meta"]["engine_version"]
    assert body["meta"]["precision_mode"]

    assert isinstance(body["diagnostics"], dict)
    assert body["diagnostics"]["nip_days"] >= 0
    assert body["diagnostics"]["reset_days"] >= 0
    assert body["diagnostics"]["effective_period_start"]

    assert isinstance(body["audit"], dict)
    assert isinstance(body["audit"]["counts"], dict)
    assert body["audit"]["counts"]


def test_core_analytics_responses_emit_shared_footer_parity(client):
    twr_payload = {
        "portfolio_id": "FOOTER_TWR",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "calculation_id": str(uuid4()),
        "valuation_points": [
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
    }
    mwr_payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "FOOTER_MWR",
        "begin_mv": 100000.0,
        "end_mv": 115000.0,
        "as_of": "2025-12-31",
        "cash_flows": [
            {"amount": 10000.0, "date": "2025-03-15"},
            {"amount": -5000.0, "date": "2025-09-20"},
        ],
        "mwr_method": "XIRR",
        "annualization": {"enabled": True, "basis": "ACT/365"},
    }
    contribution_payload = {
        "portfolio_id": "FOOTER_CONTRIBUTION",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
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
                }
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
                    }
                ],
            }
        ],
    }
    attribution_payload = {
        "portfolio_id": "FOOTER_ATTRIBUTION",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "SI", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1018.5}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"sector": "Tech"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612}],
            },
            {
                "instrument_id": "JNJ",
                "meta": {"sector": "Health"},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 406.5}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 0.5}],
            },
            {
                "key": {"sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.5}],
            },
        ],
    }

    endpoint_payloads = {
        "/performance/twr": twr_payload,
        "/performance/mwr": mwr_payload,
        "/performance/contribution": contribution_payload,
        "/performance/attribution": attribution_payload,
    }

    for endpoint, payload in endpoint_payloads.items():
        response = client.post(endpoint, json=payload)

        assert response.status_code == 200, endpoint
        _assert_shared_footer(response.json())
