# app/core/handlers.py
import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    InvalidInputDataError,
    MissingConfigurationError,
    PerformanceCalculatorError,
)
from core.errors import APIError

logger = logging.getLogger(__name__)


async def performance_calculator_exception_handler(request: Request, exc: PerformanceCalculatorError):
    """
    Handles PerformanceCalculatorError and its subclasses, returning a 500 or 400 HTTP response.
    """
    logger.error(f"PerformanceCalculatorError caught: {exc.message}", exc_info=True)

    if isinstance(exc, (InvalidInputDataError, MissingConfigurationError)):
        status_code = status.HTTP_400_BAD_REQUEST
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    return JSONResponse(status_code=status_code, content={"detail": f"Calculation Error: {exc.message}"})


async def core_api_error_exception_handler(request: Request, exc: APIError):
    """Maps framework-neutral core API errors at the FastAPI boundary."""
    logger.warning("Core APIError caught: %s", exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
