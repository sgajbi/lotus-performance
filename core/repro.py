# core/repro.py
import hashlib
import json
from typing import Any

from pydantic import BaseModel


def _canonicalize_value(value: BaseModel | dict[str, Any], *, engine_version: str) -> tuple[str, str]:
    """
    Generates a deterministic hash for a given canonical value and engine version.

    Returns a tuple of (input_fingerprint, calculation_hash).
    """
    if isinstance(value, BaseModel):
        request_dict = value.model_dump(mode="json")
    else:
        request_dict = value

    # Use the standard json library to create a canonical string with sorted keys.
    canonical_string = json.dumps(request_dict, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    input_fingerprint = f"sha256:{hashlib.sha256(canonical_string.encode('utf-8')).hexdigest()}"

    # The calculation_hash includes the engine version
    full_string_to_hash = canonical_string + engine_version
    calculation_hash = f"sha256:{hashlib.sha256(full_string_to_hash.encode('utf-8')).hexdigest()}"

    return input_fingerprint, calculation_hash


def generate_canonical_hash(request_model: BaseModel, engine_version: str) -> tuple[str, str]:
    return _canonicalize_value(request_model, engine_version=engine_version)


def generate_canonical_hash_from_value(
    request_value: BaseModel | dict[str, Any],
    engine_version: str,
) -> tuple[str, str]:
    return _canonicalize_value(request_value, engine_version=engine_version)
