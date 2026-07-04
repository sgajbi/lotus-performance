# common/enums.py
from enum import Enum


class Frequency(str, Enum):
    """Defines the supported frequency types for performance breakdowns."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class PeriodType(str, Enum):
    """Defines the supported period types for performance calculation."""

    MTD = "MTD"
    QTD = "QTD"
    YTD = "YTD"
    SI = "SI"
    ITD = "SI"
    ONE_YEAR = "1Y"
    THREE_YEARS = "3Y"
    FIVE_YEARS = "5Y"
    EXPLICIT = "EXPLICIT"


_PERIOD_ALIAS_TO_CANONICAL_CODE = {
    "ITD": "SI",
    "INCEPTION_TO_DATE": "SI",
    "SINCE_INCEPTION": "SI",
}


def canonical_performance_period_code(value: object) -> object:
    if isinstance(value, PeriodType):
        return value.value
    if not isinstance(value, str):
        return value
    return _PERIOD_ALIAS_TO_CANONICAL_CODE.get(value, value)


class AttributionMode(str, Enum):
    """Defines the input modes for the attribution engine."""

    BY_INSTRUMENT = "by_instrument"
    BY_GROUP = "by_group"


class AttributionModel(str, Enum):
    """Defines the supported Brinson-style attribution models."""

    BRINSON_FACHLER = "BF"
    BRINSON_HOOD_BEEBOWER = "BHB"


class LinkingMethod(str, Enum):
    """Defines the supported methods for linking multi-period attribution effects."""

    CARINO = "carino"
    LOGARITHMIC = "log"
    NONE = "none"


class WeightingScheme(str, Enum):
    """Defines the supported weighting schemes for contribution analysis."""

    BOD = "BOD"
    AVG_CAPITAL = "AVG_CAPITAL"
    TWR_DENOM = "TWR_DENOM"
