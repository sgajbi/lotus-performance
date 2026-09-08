from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AppliedCurrencyEvidence(BaseModel):
    """Evidence for the currency actually applied to published analytics."""

    model_config = ConfigDict(extra="forbid")

    portfolio_base_currency: str = Field(description="Portfolio base currency used by the calculation.")
    requested_report_ccy: str | None = Field(description="Reporting currency requested by the caller, if any.")
    applied_report_ccy: str | None = Field(
        description="Currency actually applied to the published result; null for local-only multi-currency output."
    )
    restated: bool = Field(description="Whether FX rates were applied to restate source-currency values or returns.")
    currency_mode_applied: Literal["BASE_ONLY", "LOCAL_ONLY", "BOTH"] = Field(
        description="Currency calculation mode actually applied."
    )
    fx_source: Literal["caller_supplied", "source_preconverted", "none"] = Field(
        description="Origin of FX rates or pre-converted return components actually applied to the result."
    )
    fx_coverage: Literal["complete", "none"] = Field(
        description="Coverage of required applied FX pairs and exact fixing dates; partial coverage is refused."
    )
    fixing_policy: Literal["EOD_EXACT_PRIOR_AND_CURRENT", "SOURCE_PRECONVERTED_RETURN_COMPONENTS"] = Field(
        description=(
            "Applied conversion policy: exact prior/current EOD caller rates, or source-provided "
            "base/local/FX return components that require no engine rate fixing."
        )
    )
    applied_pairs: list[str] = Field(
        default_factory=list,
        description="Source/reporting currency pairs whose supplied rates were applied.",
    )
    reason: str = Field(description="Bounded explanation of the applied-currency outcome.")
