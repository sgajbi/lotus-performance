"""Exact product-dispatched model methods; decoding never confers approval."""

from typing import Annotated

from pydantic import Field, TypeAdapter

from app.models.composite_model_fees import CompositePeriodicModelFeeProfile
from app.models.composite_scheduled_model_fees import CompositeScheduledModelFeeProfile

CompositeModelFeeProfile = Annotated[
    CompositePeriodicModelFeeProfile | CompositeScheduledModelFeeProfile,
    Field(discriminator="product_name"),
]
_PROFILE = TypeAdapter(CompositeModelFeeProfile)


def decode_model_fee_profile(wire: dict) -> CompositePeriodicModelFeeProfile | CompositeScheduledModelFeeProfile:
    return _PROFILE.validate_python(wire)
