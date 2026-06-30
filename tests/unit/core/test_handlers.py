# tests/unit/core/test_handlers.py
import json

import pytest
from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError

from app.api.http_status import HTTP_422_UNPROCESSABLE
from app.core.exceptions import (
    CalculationLogicError,
    InvalidInputDataError,
    MissingConfigurationError,
)
from app.core.handlers import (
    core_api_error_exception_handler,
    http_exception_handler,
    performance_calculator_exception_handler,
    request_validation_exception_handler,
)
from app.observability import correlation_id_var, request_id_var
from core.errors import APIBadRequestError, APIConflictError, APIServiceUnavailableError


def _response_json(response):
    return json.loads(response.body.decode())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_class, expected_status_code, expected_detail",
    [
        (InvalidInputDataError, status.HTTP_400_BAD_REQUEST, "A test error occurred"),
        (MissingConfigurationError, status.HTTP_400_BAD_REQUEST, "A test error occurred"),
        (
            CalculationLogicError,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "The service encountered an internal error. Use the correlation_id for support.",
        ),
    ],
)
async def test_performance_calculator_exception_handler(exception_class, expected_status_code, expected_detail):
    """
    Tests that the exception handler maps different exception types to the
    correct HTTP status codes.
    """
    test_message = "A test error occurred"
    exc = exception_class(test_message)
    mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})

    response = await performance_calculator_exception_handler(mock_request, exc)

    assert response.status_code == expected_status_code
    body = _response_json(response)
    assert body["detail"] == expected_detail
    assert body["message"] == expected_detail
    assert body["error_code"] == "CALCULATION_ERROR"


@pytest.mark.asyncio
async def test_performance_calculator_exception_handler_redacts_internal_500_text():
    exc = CalculationLogicError("internal solver secret")
    mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})

    response = await performance_calculator_exception_handler(mock_request, exc)

    body = _response_json(response)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "internal solver secret" not in response.body.decode()
    assert body["retryable"] is True


@pytest.mark.asyncio
async def test_core_api_error_exception_handler_maps_status_and_detail():
    mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})
    exc = APIBadRequestError("Invalid field value")

    response = await core_api_error_exception_handler(mock_request, exc)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    body = _response_json(response)
    assert body["detail"] == "Invalid field value"
    assert body["message"] == "Invalid field value"
    assert body["error_code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
async def test_core_api_error_exception_handler_preserves_retryability_metadata():
    mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})
    exc = APIServiceUnavailableError("stateful source unavailable")

    response = await core_api_error_exception_handler(mock_request, exc)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    body = _response_json(response)
    assert body["detail"] == "The service encountered an internal error. Use the correlation_id for support."
    assert body["error_code"] == "SOURCE_UNAVAILABLE"
    assert body["retryable"] is True


@pytest.mark.asyncio
async def test_core_api_error_exception_handler_preserves_response_headers():
    mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})
    exc = APIConflictError(
        {"code": "cooldown_active", "message": "Wait before retrying."},
        headers={"Retry-After": "60"},
    )

    response = await core_api_error_exception_handler(mock_request, exc)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.headers["retry-after"] == "60"
    body = _response_json(response)
    assert body["error_code"] == "cooldown_active"
    assert body["retryable"] is False


@pytest.mark.asyncio
async def test_http_exception_handler_preserves_coded_detail_and_observability_context():
    correlation_token = correlation_id_var.set("corr-test")
    request_token = request_id_var.set("req-test")
    try:
        mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})
        exc = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COMPOSITE_NOT_FOUND", "message": "Composite definition not found."},
        )

        response = await http_exception_handler(mock_request, exc)
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)

    body = _response_json(response)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert body["detail"] == {"code": "COMPOSITE_NOT_FOUND", "message": "Composite definition not found."}
    assert body["error_code"] == "COMPOSITE_NOT_FOUND"
    assert body["message"] == "Composite definition not found."
    assert body["correlation_id"] == "corr-test"
    assert body["request_id"] == "req-test"
    assert body["source"] == "lotus-performance"
    assert body["retryable"] is False


@pytest.mark.asyncio
async def test_http_exception_handler_redacts_raw_500_detail():
    mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})
    exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="database password leaked")

    response = await http_exception_handler(mock_request, exc)

    body = _response_json(response)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "database password leaked" not in response.body.decode()
    assert body["error_code"] == "INTERNAL_SERVER_ERROR"
    assert body["retryable"] is True


@pytest.mark.asyncio
async def test_request_validation_exception_handler_returns_machine_readable_envelope():
    mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})
    exc = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "portfolio_id"),
                "msg": "Field required",
                "input": {},
            }
        ]
    )

    response = await request_validation_exception_handler(mock_request, exc)

    body = _response_json(response)
    assert response.status_code == HTTP_422_UNPROCESSABLE
    assert body["detail"] == "Request validation failed."
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["message"] == "Request validation failed."
    assert body["validation_errors"][0]["loc"] == ["body", "portfolio_id"]
