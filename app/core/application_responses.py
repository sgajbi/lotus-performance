from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.core.async_polling import ASYNC_RETRY_AFTER_HEADER


@dataclass(frozen=True)
class ApplicationHttpResponse:
    """Framework-neutral application response with HTTP mapping metadata."""

    status_code: int
    content: Any
    headers: dict[str, str] | None = None


def accepted_application_response(model: BaseModel) -> ApplicationHttpResponse:
    content = model.model_dump(mode="json")
    headers = _accepted_response_headers(content)
    return ApplicationHttpResponse(status_code=202, content=content, headers=headers)


def _accepted_response_headers(content: Any) -> dict[str, str] | None:
    if not isinstance(content, dict):
        return None
    recommended_poll_after_seconds = content.get("recommended_poll_after_seconds")
    if not isinstance(recommended_poll_after_seconds, int):
        return None
    return {ASYNC_RETRY_AFTER_HEADER: str(recommended_poll_after_seconds)}
