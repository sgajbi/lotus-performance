from __future__ import annotations

from typing import TypeVar

from fastapi.responses import JSONResponse

from app.core.application_responses import ApplicationHttpResponse

ResponseT = TypeVar("ResponseT")


def to_fastapi_response(response: ResponseT | ApplicationHttpResponse) -> ResponseT | JSONResponse:
    if isinstance(response, ApplicationHttpResponse):
        return JSONResponse(status_code=response.status_code, content=response.content, headers=response.headers)
    return response
