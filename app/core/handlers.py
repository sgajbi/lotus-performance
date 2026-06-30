# app/core/handlers.py
import logging

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.http_status import HTTP_422_UNPROCESSABLE
from app.core.exceptions import (
    InvalidInputDataError,
    MissingConfigurationError,
    PerformanceCalculatorError,
)
from app.services.error_details import safe_error_envelope, validation_error_envelope
from core.errors import APIError

logger = logging.getLogger(__name__)


async def performance_calculator_exception_handler(request: Request, exc: PerformanceCalculatorError):
    """
    Handles PerformanceCalculatorError and its subclasses, returning a 500 or 400 HTTP response.
    """
    del request
    logger.error(f"PerformanceCalculatorError caught: {exc.message}", exc_info=True)

    if isinstance(exc, (InvalidInputDataError, MissingConfigurationError)):
        status_code = status.HTTP_400_BAD_REQUEST
        public_message = exc.message
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        public_message = None

    return JSONResponse(
        status_code=status_code,
        content=safe_error_envelope(
            status_code=status_code,
            detail=exc.message,
            error_code="CALCULATION_ERROR",
            message=public_message,
            retryable=status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR,
        ),
    )


async def core_api_error_exception_handler(request: Request, exc: APIError):
    """Maps framework-neutral core API errors at the FastAPI boundary."""
    del request
    logger.warning("Core APIError caught: %s", exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=safe_error_envelope(
            status_code=exc.status_code,
            detail=exc.detail,
            error_code=exc.error_code,
            retryable=exc.retryable,
        ),
        headers=exc.headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    """Maps FastAPI HTTP exceptions to the governed public error envelope."""
    del request
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content=safe_error_envelope(status_code=exc.status_code, detail=exc.detail),
        headers=headers,
    )


async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Maps request validation failures without exposing framework internals as the primary detail."""
    del request
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE,
        content=validation_error_envelope(exc.errors()),
    )
