"""Static BF examples compiled from the capability's executable fixture factory."""

import json
from importlib.resources import files
from typing import Any

from app.models.composite_attribution import (
    CompositeAttributionAcceptedResponse,
    CompositeAttributionRequest,
    CompositeAttributionResponse,
)
from app.models.platform_surfaces import ErrorDetailResponse
from app.services.error_details import safe_error_envelope


def attribution_openapi_examples() -> dict[str, Any]:
    """Validate packaged DTOs without acquiring sources, approving or calculating."""
    payload = json.loads(
        files("app").joinpath("api", "examples", "composite_attribution.json").read_text(encoding="utf-8")
    )
    models = {
        "request": CompositeAttributionRequest,
        "correction_request": CompositeAttributionRequest,
        "accepted": CompositeAttributionAcceptedResponse,
        "pending": CompositeAttributionAcceptedResponse,
        "original_ready": CompositeAttributionResponse,
        "original_replay": CompositeAttributionResponse,
        "corrected_ready": CompositeAttributionResponse,
    }
    return {
        **{name: model.model_validate(payload[name]).model_dump(mode="json") for name, model in models.items()},
        "errors": {
            name: ErrorDetailResponse.model_validate(value).model_dump(mode="json", exclude_unset=True)
            for name, value in payload["errors"].items()
        },
    }


def named_attribution_examples(examples: dict[str, Any], *names: str) -> dict[str, Any]:
    return {"bf_" + name: {"value": examples[name]} for name in names}


def missing_composite_analysis_example() -> dict[str, Any]:
    """The shared result route currently dispatches an absent job to its pooled reader."""
    envelope = safe_error_envelope(status_code=404, detail="Pooled calculation is absent in the verified tenant.")
    return {key: value for key, value in envelope.items() if key not in {"request_id", "correlation_id"}}


def restore_attribution_example_values(schema: dict[str, Any]) -> None:
    """FastAPI's OpenAPI encoder drops None; restore exact packaged BF values."""
    examples = attribution_openapi_examples()
    values = {**examples, **examples["errors"]}
    for path, method in (
        ("/performance/composites/analytics", "post"),
        ("/performance/composites/analytics/results/{calculation_id}", "get"),
    ):
        operation = schema.get("paths", {}).get(path, {}).get(method, {})
        contents = [operation.get("requestBody", {}), *operation.get("responses", {}).values()]
        for content in contents:
            for name, example in content.get("content", {}).get("application/json", {}).get("examples", {}).items():
                if name.startswith("bf_") and name[3:] in values:
                    example["value"] = values[name[3:]]
