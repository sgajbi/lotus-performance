# core/errors.py
from typing import Any

HTTP_400_BAD_REQUEST = 400
HTTP_401_UNAUTHORIZED = 401
HTTP_403_FORBIDDEN = 403
HTTP_404_NOT_FOUND = 404
HTTP_408_REQUEST_TIMEOUT = 408
HTTP_409_CONFLICT = 409
HTTP_422_UNPROCESSABLE = 422
HTTP_429_TOO_MANY_REQUESTS = 429
HTTP_500_INTERNAL_SERVER_ERROR = 500
HTTP_502_BAD_GATEWAY = 502
HTTP_503_SERVICE_UNAVAILABLE = 503
HTTP_504_GATEWAY_TIMEOUT = 504


class APIError(ValueError):
    """Framework-neutral core error with HTTP mapping metadata for the app boundary."""

    def __init__(
        self,
        status_code: int,
        detail: Any,
        *,
        error_code: str | None = None,
        retryable: bool | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        self.retryable = retryable
        self.headers = headers


class APIBadRequestError(APIError):
    """To be used for 400 Bad Request errors (validation, schema issues)."""

    def __init__(self, detail: Any = "Bad Request", *, error_code: str | None = None):
        super().__init__(status_code=HTTP_400_BAD_REQUEST, detail=detail, error_code=error_code)


class APINotFoundError(APIError):
    """To be used for 404 Not Found errors."""

    def __init__(self, detail: Any = "Not Found", *, error_code: str | None = None):
        super().__init__(status_code=HTTP_404_NOT_FOUND, detail=detail, error_code=error_code)


class APIUnprocessableEntityError(APIError):
    """To be used for 422 Unprocessable Entity errors (valid request, but data is insufficient)."""

    def __init__(self, detail: Any = "Unprocessable Entity", *, error_code: str | None = None):
        super().__init__(status_code=HTTP_422_UNPROCESSABLE, detail=detail, error_code=error_code)


class APIConflictError(APIError):
    """To be used for 409 Conflict errors (e.g., overlapping hierarchies)."""

    def __init__(
        self,
        detail: Any = "Conflict",
        *,
        error_code: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(
            status_code=HTTP_409_CONFLICT,
            detail=detail,
            error_code=error_code,
            headers=headers,
        )


class APIInternalServerError(APIError):
    """To be used for unexpected service failures mapped at the API boundary."""

    def __init__(self, detail: Any = "Internal Server Error", *, error_code: str | None = None):
        super().__init__(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            error_code=error_code,
            retryable=True,
        )


class APIServiceUnavailableError(APIError):
    """To be used for retryable upstream or dependency outages."""

    def __init__(self, detail: Any = "Service Unavailable", *, error_code: str | None = None):
        super().__init__(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
            error_code=error_code,
            retryable=True,
        )
