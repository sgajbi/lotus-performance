from dataclasses import dataclass

from engine.exceptions import EngineCalculationError, InvalidEngineInputError


@dataclass(frozen=True)
class EngineExceptionHttpMapping:
    status_code: int
    detail: str
    failure_message: str


def map_engine_exception_to_http_error(exc: Exception) -> EngineExceptionHttpMapping | None:
    if isinstance(exc, InvalidEngineInputError):
        detail = f"Invalid Input: {exc.message}"
        return EngineExceptionHttpMapping(status_code=400, detail=detail, failure_message=detail)
    if isinstance(exc, EngineCalculationError):
        detail = f"Calculation Error: {exc.message}"
        return EngineExceptionHttpMapping(status_code=500, detail=detail, failure_message=detail)
    return None
