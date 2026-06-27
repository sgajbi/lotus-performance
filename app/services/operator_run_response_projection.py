from __future__ import annotations

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
    return response_builder(**asdict(cast(Any, evidence)))
