from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any, TypeVar, cast

ResponseT = TypeVar("ResponseT")


def build_operator_run_response_from_evidence(
    response_builder: Callable[..., ResponseT],
    evidence: object,
) -> ResponseT:
    """Build an operator-run API response from a dataclass evidence payload."""

    if isinstance(evidence, type) or not is_dataclass(evidence):
        raise TypeError("operator run evidence must be a dataclass instance")
    return build_operator_run_response_from_mapping(response_builder, asdict(cast(Any, evidence)))


def build_operator_run_response_from_mapping(
    response_builder: Callable[..., ResponseT],
    payload: dict[str, Any],
) -> ResponseT:
    """Build an operator-run API response from a persisted evidence payload mapping."""

    signature = inspect.signature(response_builder)
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return response_builder(**payload)
    response_fields = {
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }
    return response_builder(**{key: value for key, value in payload.items() if key in response_fields})
