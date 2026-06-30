from __future__ import annotations

from typing import TypeVar

from core.errors import APIBadRequestError

T = TypeVar("T")


def require_input_mode_payload(payload: T | None, *, payload_name: str, mode_name: str) -> T:
    """Return the mode payload or raise the shared service-boundary validation error."""
    if payload is None:
        raise APIBadRequestError(
            detail=f"{payload_name} is required when input_mode={mode_name}",
        )
    return payload


def require_stateless_input(payload: T | None) -> T:
    return require_input_mode_payload(payload, payload_name="stateless_input", mode_name="stateless")


def require_stateful_input(payload: T | None) -> T:
    return require_input_mode_payload(payload, payload_name="stateful_input", mode_name="stateful")
