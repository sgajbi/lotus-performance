"""Additive metric dispatch preserving the original annual validation envelope."""

from typing import Annotated

from pydantic import Discriminator, Field, Tag, ValidationError, WrapValidator

from app.models.composite_annual_dispersion import CompositeAnnualDispersionRequest, CompositeAnnualDispersionResponse
from app.models.composite_fee_drag import CompositeFeeDragRequest, CompositeFeeDragResponse
from app.models.composite_linked_contribution import (
    CompositeLinkedContributionRequest,
    CompositeLinkedContributionResponse,
)
from app.models.composite_pooled_mwr import CompositePooledMWRRequest, CompositePooledMWRResponse


def _analytics_metric(value):
    return (
        value.get("metric_id", "ANNUAL_MEMBER_DISPERSION")
        if isinstance(value, dict)
        else getattr(value, "metric_id", "ANNUAL_MEMBER_DISPERSION")
    )


def _preserve_annual_errors(value, handler):
    try:
        return handler(value)
    except ValidationError as error:
        if _analytics_metric(value) != "ANNUAL_MEMBER_DISPERSION":
            raise
        errors = error.errors(include_url=False)
        for item in errors:
            if item["loc"] and item["loc"][0] == "ANNUAL_MEMBER_DISPERSION":
                item["loc"] = item["loc"][1:]
        raise ValidationError.from_exception_data(error.title, errors) from error


CompositeAnalyticsRequest = Annotated[
    Annotated[CompositeAnnualDispersionRequest, Tag("ANNUAL_MEMBER_DISPERSION")]
    | Annotated[CompositeLinkedContributionRequest, Tag("LINKED_MEMBER_CONTRIBUTION")]
    | Annotated[CompositePooledMWRRequest, Tag("POOLED_MONEY_WEIGHTED_RETURN")]
    | Annotated[CompositeFeeDragRequest, Tag("MODEL_FEE_DRAG")],
    Discriminator(_analytics_metric),
    WrapValidator(_preserve_annual_errors),
    Field(
        json_schema_extra={
            "discriminator": {
                "propertyName": "metric_id",
                "mapping": {
                    "ANNUAL_MEMBER_DISPERSION": "#/components/schemas/CompositeAnnualDispersionRequest",
                    "LINKED_MEMBER_CONTRIBUTION": "#/components/schemas/CompositeLinkedContributionRequest",
                    "POOLED_MONEY_WEIGHTED_RETURN": "#/components/schemas/CompositePooledMWRRequest",
                    "MODEL_FEE_DRAG": "#/components/schemas/CompositeFeeDragRequest",
                },
            }
        }
    ),
]

CompositeAnalyticsResponse = Annotated[
    CompositeAnnualDispersionResponse
    | CompositeLinkedContributionResponse
    | CompositePooledMWRResponse
    | CompositeFeeDragResponse,
    Field(discriminator="metric_id"),
]
