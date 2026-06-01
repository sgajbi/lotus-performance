from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from app.services.input_mode_validation import require_stateful_input, require_stateless_input


def test_require_stateless_input_returns_present_payload():
    payload = SimpleNamespace(name="stateless")

    assert require_stateless_input(payload) is payload


def test_require_stateful_input_returns_present_payload():
    payload = SimpleNamespace(name="stateful")

    assert require_stateful_input(payload) is payload


def test_require_stateless_input_raises_shared_mode_error():
    with pytest.raises(HTTPException) as exc_info:
        require_stateless_input(None)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "stateless_input is required when input_mode=stateless"


def test_require_stateful_input_raises_shared_mode_error():
    with pytest.raises(HTTPException) as exc_info:
        require_stateful_input(None)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "stateful_input is required when input_mode=stateful"
