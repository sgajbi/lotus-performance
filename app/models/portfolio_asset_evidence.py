"""Exact normalized source assets, separate from FLOAT64 calculation output."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.composites import ReportingCurrency


class PortfolioSourceAssetObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    valuation_date: date = Field(description="Core valuation business date.", examples=["2026-01-05"])
    beginning_market_value: Decimal = Field(
        description="Exact normalized Core beginning assets in source currency, before flows.", examples=["100.001"]
    )
    ending_market_value: Decimal = Field(
        description="Exact normalized Core closing assets in source currency.", examples=["110.0011"]
    )


class PortfolioSourceAssetEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    contract_version: Literal["portfolio-source-assets.v1"] = Field(
        default="portfolio-source-assets.v1", description="Exact asset evidence contract revision."
    )
    source_owner: Literal["lotus-core"] = Field(default="lotus-core", description="Valuation source owner.")
    source_product: Literal["PortfolioTimeseriesInput"] = Field(
        default="PortfolioTimeseriesInput", description="Source product normalized for this calculation."
    )
    portfolio_currency: ReportingCurrency = Field(
        description="Core-published monetary currency, not a requested reporting currency.", examples=["USD"]
    )
    observations: list[PortfolioSourceAssetObservation] = Field(
        min_length=1, description="Canonical exact asset observations retained before public float coercion."
    )

    @model_validator(mode="after")
    def unique_ordered_dates(self) -> "PortfolioSourceAssetEvidence":
        dates = [item.valuation_date for item in self.observations]
        if dates != sorted(set(dates)):
            raise ValueError("Source asset evidence must have unique ordered valuation dates")
        return self
