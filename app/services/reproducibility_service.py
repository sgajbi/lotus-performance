from typing import Any

from pydantic import BaseModel

from core.repro import generate_canonical_hash_from_value as _generate_canonical_hash_from_value


def generate_request_fingerprint(request_value: BaseModel | dict[str, Any], engine_version: str) -> tuple[str, str]:
    return _generate_canonical_hash_from_value(request_value, engine_version)


def generate_value_fingerprint(request_value: BaseModel | dict[str, Any], engine_version: str) -> tuple[str, str]:
    return _generate_canonical_hash_from_value(request_value, engine_version)
