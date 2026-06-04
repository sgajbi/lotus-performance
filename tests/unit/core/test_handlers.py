# tests/unit/core/test_handlers.py
import pytest
from fastapi import Request, status

from app.core.exceptions import (
    CalculationLogicError,
    InvalidInputDataError,
    MissingConfigurationError,
)
from app.core.handlers import core_api_error_exception_handler, performance_calculator_exception_handler
from core.errors import APIBadRequestError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_class, expected_status_code",
    [
        (InvalidInputDataError, status.HTTP_400_BAD_REQUEST),
        (MissingConfigurationError, status.HTTP_400_BAD_REQUEST),
        (CalculationLogicError, status.HTTP_500_INTERNAL_SERVER_ERROR),
    ],
)
async def test_performance_calculator_exception_handler(exception_class, expected_status_code):
    """
    Tests that the exception handler maps different exception types to the
    correct HTTP status codes.
    """
    # 1. Arrange
    test_message = "A test error occurred"
    exc = exception_class(test_message)
    # The handler requires a Request object, but its contents are not used.
    mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})

    # 2. Act
    response = await performance_calculator_exception_handler(mock_request, exc)

    # 3. Assert
    assert response.status_code == expected_status_code
    response_body = response.body.decode()
    assert "detail" in response_body
    assert f"Calculation Error: {test_message}" in response_body


@pytest.mark.asyncio
async def test_core_api_error_exception_handler_maps_status_and_detail():
    mock_request = Request({"type": "http", "method": "POST", "url": "/mock-url"})
    exc = APIBadRequestError("Invalid field value")

    response = await core_api_error_exception_handler(mock_request, exc)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid field value" in response.body.decode()
