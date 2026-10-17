"""Internal retained scenario DTO; the public legacy CompositeDefinition is unchanged."""

from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.composite_authority import ControlledScenarioAuthorityProfileV3
from app.models.composite_controlled_annual_authority import ControlledYearAuthorityProfile
from app.models.composites import CompositeCalculationMethod, CompositeDefinition, ReportingCurrency


class ControlledScenarioCompositeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    composite_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    strategy_code: str = Field(min_length=1)
    reporting_currency: ReportingCurrency
    inception_date: date
    termination_date: date | None = None
    calculation_method: CompositeCalculationMethod = CompositeCalculationMethod.ASSET_WEIGHTED
    source_authority: ControlledScenarioAuthorityProfileV3

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if self.termination_date is not None and self.termination_date < self.inception_date:
            raise ValueError("termination_date cannot be before inception_date")
        return self


class ControlledAnnualCompositeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    composite_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    strategy_code: str = Field(min_length=1)
    reporting_currency: ReportingCurrency
    inception_date: date
    termination_date: date | None = None
    calculation_method: CompositeCalculationMethod = CompositeCalculationMethod.ASSET_WEIGHTED
    source_authority: ControlledYearAuthorityProfile

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if self.termination_date is not None and self.termination_date < self.inception_date:
            raise ValueError("termination_date cannot be before inception_date")
        return self


RetainedCompositeDefinition = (
    CompositeDefinition | ControlledScenarioCompositeDefinition | ControlledAnnualCompositeDefinition
)


def decode_retained_definition(payload) -> RetainedCompositeDefinition:
    authority = payload.get("source_authority")
    if isinstance(authority, dict) and isinstance(authority.get("payload"), dict):
        source = authority["payload"]
        if (source.get("product_name"), source.get("product_version")) == ("CompositeSourceAuthority", "v4"):
            return ControlledAnnualCompositeDefinition.model_validate(payload)
        if (source.get("product_name"), source.get("product_version")) == ("CompositeSourceAuthority", "v3"):
            return ControlledScenarioCompositeDefinition.model_validate(payload)
    return CompositeDefinition.model_validate(payload)
