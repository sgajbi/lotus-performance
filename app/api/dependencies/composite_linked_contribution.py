"""Packaged registered HTTP examples; no source acquisition or arithmetic at import."""

import json
from importlib.resources import files

from app.models.composite_linked_contribution import (
    CompositeLinkedContributionRequest,
    CompositeLinkedContributionResponse,
)
from app.models.platform_surfaces import ErrorDetailResponse


def linked_contribution_openapi_examples():
    payload = json.loads(
        files("app").joinpath("api", "examples", "composite_linked_contribution.json").read_text(encoding="utf-8")
    )
    return {
        "request": CompositeLinkedContributionRequest.model_validate(payload["request"]).model_dump(mode="json"),
        "response": CompositeLinkedContributionResponse.model_validate(payload["response"]).model_dump(mode="json"),
        "missing_request": CompositeLinkedContributionRequest.model_validate(payload["missing_request"]).model_dump(
            mode="json"
        ),
        "missing_response": ErrorDetailResponse.model_validate(payload["missing_response"]).model_dump(
            mode="json", exclude_unset=True
        ),
    }
