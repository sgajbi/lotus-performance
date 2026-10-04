import json
from importlib.resources import files
from typing import Any

from app.adapters.composite_annual_dispersion import RetainedAnnualDispersionReceiptReader
from app.models.composite_annual_comparison import CompositeAnnualComparisonRequest, CompositeAnnualComparisonResponse
from app.models.composite_annual_dispersion import CompositeAnnualDispersionRequest, CompositeAnnualDispersionResponse
from app.models.platform_surfaces import ErrorDetailResponse
from app.ports.composite_annual_dispersion import AnnualDispersionReceiptReader


def get_annual_dispersion_receipt_reader() -> AnnualDispersionReceiptReader:
    return RetainedAnnualDispersionReceiptReader()


def annual_dispersion_openapi_examples() -> dict[str, dict[str, Any]]:
    """Load static synthetic HTTP examples; no store or financial work at import."""
    payload = json.loads(
        files("app").joinpath("api", "examples", "composite_annual_dispersion.json").read_text(encoding="utf-8")
    )
    return {
        "request": CompositeAnnualDispersionRequest.model_validate(payload["request"]).model_dump(mode="json"),
        "response": CompositeAnnualDispersionResponse.model_validate(payload["response"]).model_dump(mode="json"),
        "errors": {
            name: ErrorDetailResponse.model_validate(example).model_dump(mode="json", exclude_unset=True)
            for name, example in payload["errors"].items()
        },
    }


def annual_comparison_openapi_examples() -> dict[str, dict[str, Any]]:
    """Load packaged comparison examples without acquiring sources or calculating outputs."""
    payload = json.loads(
        files("app").joinpath("api", "examples", "composite_annual_comparison.json").read_text(encoding="utf-8")
    )
    return {
        "request": CompositeAnnualComparisonRequest.model_validate(payload["request"]).model_dump(mode="json"),
        "response": CompositeAnnualComparisonResponse.model_validate(payload["response"]).model_dump(mode="json"),
        "errors": {
            name: ErrorDetailResponse.model_validate(example).model_dump(mode="json", exclude_unset=True)
            for name, example in payload["errors"].items()
        },
    }
