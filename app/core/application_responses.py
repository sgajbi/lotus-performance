from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class ApplicationHttpResponse:
    """Framework-neutral application response with HTTP mapping metadata."""

    status_code: int
    content: Any


def accepted_application_response(model: BaseModel) -> ApplicationHttpResponse:
    return ApplicationHttpResponse(status_code=202, content=model.model_dump(mode="json"))
