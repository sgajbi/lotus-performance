import importlib
import warnings

from fastapi import status

import app.api.http_status as http_status


def test_http_422_unprocessable_uses_current_starlette_status_name():
    assert http_status.HTTP_422_UNPROCESSABLE == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_http_422_unprocessable_falls_back_for_older_starlette(monkeypatch):
    monkeypatch.delattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", raising=False)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated")
        reloaded = importlib.reload(http_status)
        assert reloaded.HTTP_422_UNPROCESSABLE == status.HTTP_422_UNPROCESSABLE_ENTITY
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated")
        importlib.reload(http_status)
