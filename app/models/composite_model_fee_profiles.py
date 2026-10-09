"""Publication records retain method bytes and publisher custody without granting approval."""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.models.composite_authority import AuthorityWire, EvidenceBinding
from app.models.composite_component_model_fees import CompositeComponentModelFeeProfile
from app.models.composite_model_fee_contract import CompositeModelFeeProfile, decode_model_fee_profile

PublishedCompositeModelFeeProfile = Annotated[
    CompositeModelFeeProfile | CompositeComponentModelFeeProfile, Field(discriminator="product_name")
]


def decode_published_model_fee_profile(wire):
    if wire.get("product_name") == "CompositeComponentPeriodicModelFeeProfile":
        return CompositeComponentModelFeeProfile.model_validate(wire)
    return decode_model_fee_profile(wire)


class CompositeModelFeeProfileReceipt(AuthorityWire):
    posture: Literal["UNAPPROVED_METHOD_INPUT"] = Field(
        default="UNAPPROVED_METHOD_INPUT",
        description="Publication retains input custody; independent method approval is still required.",
    )
    binding: EvidenceBinding = Field(description="Exact immutable canonical method-profile identity and digest.")
    profile: PublishedCompositeModelFeeProfile = Field(
        description="Original complete strict method wire; publisher custody does not alter these bytes."
    )
    published_by: str = Field(
        strict=True,
        min_length=1,
        max_length=128,
        description="Original admitted publishing actor, preserved on same-content retries.",
    )
    published_at_utc: datetime = Field(
        description="Original timezone-aware UTC custody recording time; not a business effective date."
    )

    @model_validator(mode="after")
    def valid_custody(self):
        if self.published_by != self.published_by.strip() or self.published_at_utc.utcoffset() != timedelta(0):
            raise ValueError("Model-fee publication requires admitted original actor and aware custody time")
        return self
