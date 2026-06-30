# tests/unit/core/test_errors.py
from core.errors import (
    HTTP_400_BAD_REQUEST,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE,
    HTTP_503_SERVICE_UNAVAILABLE,
    APIBadRequestError,
    APIConflictError,
    APIServiceUnavailableError,
    APIUnprocessableEntityError,
)


def test_api_bad_request_error():
    """Tests the APIBadRequestError custom exception."""
    try:
        raise APIBadRequestError("Invalid field value")
    except APIBadRequestError as e:
        assert e.status_code == HTTP_400_BAD_REQUEST
        assert e.detail == "Invalid field value"


def test_api_unprocessable_entity_error():
    """Tests the APIUnprocessableEntityError custom exception."""
    try:
        raise APIUnprocessableEntityError("Calculation failed to converge")
    except APIUnprocessableEntityError as e:
        assert e.status_code == HTTP_422_UNPROCESSABLE
        assert e.detail == "Calculation failed to converge"


def test_api_conflict_error():
    """Tests the APIConflictError custom exception."""
    try:
        raise APIConflictError("Resource already exists")
    except APIConflictError as e:
        assert e.status_code == HTTP_409_CONFLICT
        assert e.detail == "Resource already exists"


def test_api_error_is_framework_neutral_value_error():
    error = APIBadRequestError("Invalid field value")
    assert isinstance(error, ValueError)


def test_api_service_unavailable_error_carries_retryability_metadata():
    error = APIServiceUnavailableError("upstream source unavailable")

    assert error.status_code == HTTP_503_SERVICE_UNAVAILABLE
    assert error.detail == "upstream source unavailable"
    assert error.retryable is True
