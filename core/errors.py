# core/errors.py
HTTP_400_BAD_REQUEST = 400
HTTP_404_NOT_FOUND = 404
HTTP_409_CONFLICT = 409
HTTP_422_UNPROCESSABLE = 422
HTTP_500_INTERNAL_SERVER_ERROR = 500
HTTP_503_SERVICE_UNAVAILABLE = 503


class APIError(ValueError):
    """Framework-neutral core error with HTTP mapping metadata for the app boundary."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        error_code: str | None = None,
        retryable: bool | None = None,
    ):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        self.retryable = retryable


class APIBadRequestError(APIError):
    """To be used for 400 Bad Request errors (validation, schema issues)."""

    def __init__(self, detail: str = "Bad Request"):
        super().__init__(status_code=HTTP_400_BAD_REQUEST, detail=detail)


class APINotFoundError(APIError):
    """To be used for 404 Not Found errors."""

    def __init__(self, detail: str = "Not Found"):
        super().__init__(status_code=HTTP_404_NOT_FOUND, detail=detail)


class APIUnprocessableEntityError(APIError):
    """To be used for 422 Unprocessable Entity errors (valid request, but data is insufficient)."""

    def __init__(self, detail: str = "Unprocessable Entity"):
        super().__init__(status_code=HTTP_422_UNPROCESSABLE, detail=detail)


class APIConflictError(APIError):
    """To be used for 409 Conflict errors (e.g., overlapping hierarchies)."""

    def __init__(self, detail: str = "Conflict"):
        super().__init__(status_code=HTTP_409_CONFLICT, detail=detail)


class APIInternalServerError(APIError):
    """To be used for unexpected service failures mapped at the API boundary."""

    def __init__(self, detail: str = "Internal Server Error"):
        super().__init__(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            retryable=True,
        )


class APIServiceUnavailableError(APIError):
    """To be used for retryable upstream or dependency outages."""

    def __init__(self, detail: str = "Service Unavailable"):
        super().__init__(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
            retryable=True,
        )
