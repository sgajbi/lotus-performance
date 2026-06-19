from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

_LOTUS_PERFORMANCE_SOURCE_SERVICE = "lotus-performance"
_OPERATOR_RUN_CONTRACT_VERSION = "v1"

ModelT = TypeVar("ModelT", bound=BaseModel)


def build_lotus_performance_operator_run_response(
    response_model: type[ModelT],
    **payload: object,
) -> ModelT:
    return response_model(
        contract_version=_OPERATOR_RUN_CONTRACT_VERSION,
        source_service=_LOTUS_PERFORMANCE_SOURCE_SERVICE,
        **payload,
    )
