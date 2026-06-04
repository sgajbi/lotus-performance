import pytest

from app.services.engine_exception_mapping_service import map_engine_exception_to_http_error
from engine.exceptions import EngineCalculationError, InvalidEngineInputError


@pytest.mark.parametrize(
    ("exc", "expected_status", "expected_detail"),
    [
        (InvalidEngineInputError("bad input"), 400, "Invalid Input: bad input"),
        (EngineCalculationError("engine failed"), 500, "Calculation Error: engine failed"),
    ],
)
def test_map_engine_exception_to_http_error_maps_known_engine_exceptions(
    exc: Exception,
    expected_status: int,
    expected_detail: str,
):
    mapping = map_engine_exception_to_http_error(exc)

    assert mapping is not None
    assert mapping.status_code == expected_status
    assert mapping.detail == expected_detail
    assert mapping.failure_message == expected_detail


def test_map_engine_exception_to_http_error_ignores_unknown_exceptions():
    assert map_engine_exception_to_http_error(RuntimeError("boom")) is None
