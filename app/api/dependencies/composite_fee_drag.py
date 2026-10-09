"""Complete controlled HTTP examples; no financial acquisition or calculation at import."""

import json
from importlib.resources import files

from app.models.composite_fee_drag import CompositeFeeDragRequest, CompositeFeeDragResponse
from app.models.platform_surfaces import ErrorDetailResponse


def fee_drag_openapi_examples():
    payload = json.loads(
        files("app").joinpath("api", "examples", "composite_fee_drag.json").read_text(encoding="utf-8")
    )
    return {
        "request": CompositeFeeDragRequest.model_validate(payload["request"]).model_dump(mode="json"),
        "response": CompositeFeeDragResponse.model_validate(payload["response"]).model_dump(mode="json"),
        "missing_request": CompositeFeeDragRequest.model_validate(payload["missing_request"]).model_dump(mode="json"),
        "missing_response": ErrorDetailResponse.model_validate(payload["missing_response"]).model_dump(
            mode="json", exclude_unset=True
        ),
    }
