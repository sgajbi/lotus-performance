# tests/unit/core/test_errors.py
import importlib
import warnings

from fastapi import status

import core.errors as errors_module
from core.errors import APIBadRequestError, APIConflictError, APIUnprocessableEntityError

if hasattr(status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    HTTP_422_UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_CONTENT
else:
    HTTP_422_UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_ENTITY


def test_api_bad_request_error():
    """Tests the APIBadRequestError custom exception."""
    try:
        raise APIBadRequestError("Invalid field value")
    except APIBadRequestError as e:
        assert e.status_code == status.HTTP_400_BAD_REQUEST
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
        assert e.status_code == status.HTTP_409_CONFLICT
        assert e.detail == "Resource already exists"


def test_legacy_422_fallback_branch(monkeypatch):
    if hasattr(status, "HTTP_422_UNPROCESSABLE_CONTENT"):
        monkeypatch.delattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", raising=False)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated")
            reloaded = importlib.reload(errors_module)
            assert reloaded.HTTP_422_UNPROCESSABLE == status.HTTP_422_UNPROCESSABLE_ENTITY
            importlib.reload(errors_module)
