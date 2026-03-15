from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StatefulDimensionName = Literal["asset_class", "sector", "country"]


class StatefulDimensionFilter(BaseModel):
    dimension: StatefulDimensionName
    values: list[str] = Field(min_length=1)


class StatefulPositionFilters(BaseModel):
    security_ids: list[str] = Field(default_factory=list)
    position_ids: list[str] = Field(default_factory=list)
    dimension_filters: list[StatefulDimensionFilter] = Field(default_factory=list)
