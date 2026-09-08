# engine/config.py
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal, Optional

from common.enums import PeriodType
from core.envelope import DataPolicy, FXRequestBlock, HedgingRequestBlock


class PrecisionMode(str, Enum):
    """
    Defines the calculation precision modes for the engine.
    - FLOAT64: Uses standard NumPy float64 for high performance.
    - DECIMAL_STRICT: Uses Python's Decimal type for auditable precision.
    """

    FLOAT64 = "FLOAT64"
    DECIMAL_STRICT = "DECIMAL_STRICT"


@dataclass(frozen=True)
class FeatureFlags:
    """
    Container for feature flags to enable/disable experimental or alternative logic.
    """

    use_nip_v2_rule: bool = False


@dataclass(frozen=True)
class EngineConfig:
    """
    A comprehensive, immutable configuration object for the performance engine.
    This object encapsulates all settings required for a calculation run.
    """

    performance_start_date: date
    report_end_date: date
    metric_basis: Literal["NET", "GROSS"]
    period_type: PeriodType
    rounding_precision: int = 4
    report_start_date: Optional[date] = None
    precision_mode: PrecisionMode = PrecisionMode.FLOAT64
    feature_flags: FeatureFlags = field(default_factory=FeatureFlags)
    data_policy: Optional[DataPolicy] = None

    currency_mode: Optional[Literal["BASE_ONLY", "LOCAL_ONLY", "BOTH"]] = "BASE_ONLY"
    report_ccy: Optional[str] = "USD"
    source_currency: Optional[str] = None
    fx: Optional[FXRequestBlock] = None
    hedging: Optional[HedgingRequestBlock] = None
