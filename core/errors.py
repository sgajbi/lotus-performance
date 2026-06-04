# core/errors.py
HTTP_400_BAD_REQUEST = 400
HTTP_409_CONFLICT = 409
HTTP_422_UNPROCESSABLE = 422


class APIError(ValueError):
    """Framework-neutral core error with HTTP mapping metadata for the app boundary."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class APIBadRequestError(APIError):
    """To be used for 400 Bad Request errors (validation, schema issues)."""

    def __init__(self, detail: str = "Bad Request"):
        super().__init__(status_code=HTTP_400_BAD_REQUEST, detail=detail)


class APIUnprocessableEntityError(APIError):
    """To be used for 422 Unprocessable Entity errors (valid request, but data is insufficient)."""

    def __init__(self, detail: str = "Unprocessable Entity"):
        super().__init__(status_code=HTTP_422_UNPROCESSABLE, detail=detail)


class APIConflictError(APIError):
    """To be used for 409 Conflict errors (e.g., overlapping hierarchies)."""

    def __init__(self, detail: str = "Conflict"):
        super().__init__(status_code=HTTP_409_CONFLICT, detail=detail)
