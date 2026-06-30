from types import SimpleNamespace

import pytest

from app.services.input_mode_validation import require_stateful_input, require_stateless_input
from core.errors import HTTP_400_BAD_REQUEST, APIError


def test_require_stateless_input_returns_present_payload():
    payload = SimpleNamespace(name="stateless")

    assert require_stateless_input(payload) is payload


def test_require_stateful_input_returns_present_payload():
    payload = SimpleNamespace(name="stateful")

    assert require_stateful_input(payload) is payload


def test_require_stateless_input_raises_shared_mode_error():
    with pytest.raises(APIError) as exc_info:
        require_stateless_input(None)

    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "stateless_input is required when input_mode=stateless"


def test_require_stateful_input_raises_shared_mode_error():
    with pytest.raises(APIError) as exc_info:
        require_stateful_input(None)

    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "stateful_input is required when input_mode=stateful"
