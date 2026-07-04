from app.models.requests import PerformanceRequest
from app.services.reproducibility_service import generate_request_fingerprint, generate_value_fingerprint
from core.repro import generate_canonical_hash, generate_canonical_hash_from_value


def _performance_request() -> PerformanceRequest:
    return PerformanceRequest.model_validate(
        {
            "portfolio_id": "TEST_HASH",
            "performance_start_date": "2024-12-31",
            "report_end_date": "2025-01-02",
            "metric_basis": "NET",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            ],
        }
    )


def test_generate_request_fingerprint_matches_core_model_hash():
    request = _performance_request()

    assert generate_request_fingerprint(request, "v1.0.0") == generate_canonical_hash(request, "v1.0.0")


def test_generate_request_fingerprint_matches_core_value_hash():
    payload = {"portfolio_id": "P1", "periods": ["YTD", "SI"]}

    assert generate_request_fingerprint(payload, "v1.0.0") == generate_canonical_hash_from_value(payload, "v1.0.0")


def test_generate_value_fingerprint_matches_core_value_hash():
    payload = {"portfolio_id": "P1", "periods": ["YTD", "SI"]}

    assert generate_value_fingerprint(payload, "v1.0.0") == generate_canonical_hash_from_value(payload, "v1.0.0")
