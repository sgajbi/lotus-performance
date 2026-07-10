# tests/unit/core/test_repro.py
import pytest

from app.models.requests import PerformanceRequest
from core.repro import generate_canonical_hash, generate_canonical_hash_from_value


@pytest.fixture
def sample_twr_request():
    """Provides a sample PerformanceRequest object."""
    payload = {
        "portfolio_id": "TEST_HASH",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-02",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.0},
            {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
        ],
    }
    return PerformanceRequest.model_validate(payload)


def test_generate_canonical_hash_is_deterministic(sample_twr_request):
    """Tests that the hash is the same for two identical requests."""
    _, hash1 = generate_canonical_hash(sample_twr_request, "v1.0.0")
    _, hash2 = generate_canonical_hash(sample_twr_request, "v1.0.0")
    assert hash1 == hash2


def test_generate_canonical_hash_is_sensitive_to_data_change(sample_twr_request):
    """Tests that the hash changes if a data value changes."""
    _, hash1 = generate_canonical_hash(sample_twr_request, "v1.0.0")
    sample_twr_request.valuation_points[0].end_mv = 1021.0  # Change one value
    _, hash2 = generate_canonical_hash(sample_twr_request, "v1.0.0")
    assert hash1 != hash2


def test_generate_canonical_hash_is_sensitive_to_version_change(sample_twr_request):
    """Tests that the hash changes if the engine version changes."""
    _, hash1 = generate_canonical_hash(sample_twr_request, "v1.0.0")
    _, hash2 = generate_canonical_hash(sample_twr_request, "v1.0.1")
    assert hash1 != hash2


def test_generate_canonical_hash_canonicalizes_object_key_order():
    """Tests that object key ordering does not affect canonical hash identity."""
    left = {
        "portfolio_id": "KEY_ORDER",
        "nested": {
            "report_end_date": "2025-01-02",
            "performance_start_date": "2024-12-31",
        },
    }
    right = {
        "nested": {
            "performance_start_date": "2024-12-31",
            "report_end_date": "2025-01-02",
        },
        "portfolio_id": "KEY_ORDER",
    }

    assert generate_canonical_hash_from_value(left, "v1.0.0") == generate_canonical_hash_from_value(right, "v1.0.0")


def test_generate_canonical_hash_preserves_ordered_array_identity(sample_twr_request):
    """
    Tests that ordered request arrays are part of reproducibility identity.

    A future schema-aware canonicalizer may sort selected fields by stable business keys, but the
    current contract deliberately does not globally sort arrays.
    """
    _, hash1 = generate_canonical_hash(sample_twr_request, "v1.0.0")
    sample_twr_request.valuation_points.reverse()
    _, hash2 = generate_canonical_hash(sample_twr_request, "v1.0.0")
    assert hash1 != hash2
