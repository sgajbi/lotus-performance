from app.services.inspection.subject_materialization import (
    extract_performance_request_from_payload,
    extract_resolved_execution_request_from_payload,
)


def test_extract_resolved_execution_request_accepts_wrapped_stateful_lineage_payload():
    payload = {
        "resolved_request": {
            "portfolio": {
                "portfolio_id": "PB_SG_GLOBAL_BAL_001",
                "performance_start_date": "2026-01-01",
                "metric_basis": "NET",
                "report_end_date": "2026-04-10",
                "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                "valuation_points": [
                    {
                        "perf_date": "2026-01-01",
                        "begin_mv": 1000.0,
                        "end_mv": 1001.0,
                        "bod_cf": 0.0,
                        "eod_cf": 0.0,
                        "mgmt_fees": 0.0,
                    }
                ],
            },
            "benchmark": None,
        },
        "source_input_mode": "stateful",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
    }

    resolved_request = extract_resolved_execution_request_from_payload(payload)
    performance_request = extract_performance_request_from_payload(payload)

    assert resolved_request is not None
    assert resolved_request.portfolio.portfolio_id == "PB_SG_GLOBAL_BAL_001"
    assert performance_request is not None
    assert performance_request.valuation_points[0].perf_date.isoformat() == "2026-01-01"
