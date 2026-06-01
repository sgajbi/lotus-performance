from __future__ import annotations

import json
import logging
from typing import Any


def load_json_object_or_none(
    raw_payload: str | None,
    *,
    logger: logging.Logger,
    payload_name: str,
    identity_name: str,
    identity_value: str,
) -> dict[str, Any] | None:
    if not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        logger.warning("%s invalid JSON for %s=%s.", payload_name, identity_name, identity_value)
        return None
    if not isinstance(payload, dict):
        logger.warning("%s is not an object for %s=%s.", payload_name, identity_name, identity_value)
        return None
    return payload
