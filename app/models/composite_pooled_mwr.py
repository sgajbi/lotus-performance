"""Dated monetary contracts for pooled XIRR; source authority is resolved by ports."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.models.mwr_requests import Solver
from core.envelope import Annualization, Calendar

Identifier = Annotated[str, Field(min_length=1, max_length=255)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


def _exact_source_money(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise ValueError("Source money requires an exact decimal string, integer or Decimal.")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Source money must be a valid finite decimal.") from exc
    if not amount.is_finite():
        raise ValueError("Source money must be finite.")
    return amount


ExactSourceMoney = Annotated[Decimal, BeforeValidator(_exact_source_money)]


class PooledContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompositePooledMWRRequest(PooledContract):
    calculation_id: UUID = Field(default_factory=uuid4)
    composite_id: Identifier
    metric_id: Literal["POOLED_MONEY_WEIGHTED_RETURN"] = "POOLED_MONEY_WEIGHTED_RETURN"
    method: Literal["XIRR:v1"] = "XIRR:v1"
    period_start: date
    period_end: date
    reporting_currency: Currency
    return_view: Literal["GROSS", "NET_ACTUAL", "NET_MODEL_FEE"]
    source_manifest_id: Identifier
    policy_binding_id: Identifier
    annualization: Annualization = Field(default_factory=lambda: Annualization(enabled=True, basis="ACT/365"))
    calendar: Calendar = Field(default_factory=Calendar)
    solver: Solver = Field(default_factory=Solver)
    fallback_policy: Literal["REQUIRE_XIRR", "ALLOW_MODIFIED_DIETZ"] = "REQUIRE_XIRR"
    correction_of_calculation_id: UUID | None = None

    @model_validator(mode="after")
    def require_forward_window(self):
        if self.period_end <= self.period_start:
            raise ValueError("Pooled XIRR requires a strictly positive explicit date interval.")
        if self.correction_of_calculation_id == self.calculation_id:
            raise ValueError("A correction must use a new calculation identity.")
        if self.annualization.periods_per_year is not None:
            raise ValueError("Pooled policy binds the named engine day basis; custom divisors are unsupported.")
        return self


class PooledSourcePin(PooledContract):
    pin_id: Identifier
    owner: Identifier
    product_name: Identifier
    product_version: Identifier
    revision: Identifier
    source_cut_id: Identifier
    payload_digest: Identifier
    compatibility_group: Identifier
    coverage_from: date
    coverage_to: date
    completeness: Literal["COMPLETE", "INCOMPLETE", "UNAVAILABLE"]
    page_ids: tuple[Identifier, ...]
    expected_page_count: int = Field(ge=1)


class PooledMembershipInterval(PooledContract):
    portfolio_id: Identifier
    effective_from: date
    effective_to: date
    status: Literal["INCLUDED", "EXCLUDED", "PENDING"]
    source_row_id: Identifier
    reason_code: Identifier


class PooledValuation(PooledContract):
    portfolio_id: Identifier
    economic_date: date
    role: Literal["OPENING", "TERMINAL", "ENTRY", "EXIT"]
    amount: ExactSourceMoney
    currency: Currency
    source_pin_id: Identifier
    source_row_id: Identifier
    timing: Literal["BOD", "EOD"]
    units: Literal["MONETARY_AMOUNT"] = "MONETARY_AMOUNT"


class PooledCashFlow(PooledContract):
    portfolio_id: Identifier
    economic_date: date
    source_date: date
    settlement_date: date | None = None
    payment_date: date | None = None
    amount: ExactSourceMoney
    currency: Currency
    timing: Literal["BOD", "EOD"]
    classification: Literal["EXTERNAL", "POOL_TRANSFER", "UNKNOWN"]
    flow_scope: Literal["PORTFOLIO"]
    source_pin_id: Identifier
    identity_namespace: Identifier
    identity_scope: Literal["PORTFOLIO", "SOURCE"]
    event_id: Identifier
    revision: Identifier
    lifecycle_status: Literal["ACTIVE", "REVERSED", "CANCELLED", "SUPERSEDED"]
    predecessor_event_id: Identifier | None = None
    predecessor_revision: Identifier | None = None
    transfer_group_id: Identifier | None = None
    counterparty_portfolio_id: Identifier | None = None
    units: Literal["MONETARY_AMOUNT"] = "MONETARY_AMOUNT"

    @model_validator(mode="after")
    def require_complete_predecessor(self):
        if (self.predecessor_event_id is None) != (self.predecessor_revision is None):
            raise ValueError("Flow predecessor requires both source event identity and revision.")
        if self.predecessor_event_id == self.event_id and self.predecessor_revision == self.revision:
            raise ValueError("A flow revision cannot be its own predecessor.")
        return self


class PooledFlowCoverage(PooledContract):
    portfolio_id: Identifier
    coverage_from: date
    coverage_to: date
    source_pin_id: Identifier
    complete: bool
    active_event_ids: tuple[Identifier, ...]
    explicitly_empty: bool


class PooledPolicyBinding(PooledContract):
    binding_id: Identifier
    owner: Identifier
    revision: Identifier
    content_hash: Identifier
    applicability_reference: Identifier
    method: Literal["XIRR:v1"]
    return_view: Literal["GROSS", "NET_ACTUAL", "NET_MODEL_FEE"]
    fee_basis: Identifier
    tax_basis: Identifier
    sign_convention: Literal["PORTFOLIO_IN_POSITIVE"]
    flow_lifecycle_policy: Literal["OWNER_RESOLVED_CURRENT_EFFECTIVE"]
    date_basis: Literal["EFFECTIVE_DATE", "SETTLEMENT_DATE", "PAYMENT_DATE"]
    opening_timing: Literal["BOD", "EOD"]
    terminal_timing: Literal["BOD", "EOD"]
    boundary_flow_policy: Literal["VALUES_EXCLUDE_BOUNDARY_FLOWS", "UNSUPPORTED"]
    transfer_policy: Literal["SOURCE_LINKED_RECONCILED", "NO_INTERNAL_TRANSFERS", "UNAVAILABLE"]
    entry_exit_policy: Literal["EXPLICIT_BOUNDARY_CAPITAL", "UNAVAILABLE"]
    day_count_basis: Literal["BUS/252", "ACT/365", "ACT/ACT"]
    fallback_policy: Literal["REQUIRE_XIRR", "ALLOW_MODIFIED_DIETZ"]


class PooledSourceBundle(PooledContract):
    """Port-returned original evidence; possession alone does not establish authority."""

    tenant_id: Identifier
    composite_id: Identifier
    source_manifest_id: Identifier
    definition_revision: Identifier
    definition_hash: Identifier
    membership_revision: Identifier
    membership_hash: Identifier
    population_source_pin_id: Identifier
    compatibility_reference: Identifier
    compatible_pin_ids: tuple[Identifier, ...]
    period_start: date
    period_end: date
    reporting_currency: Currency
    expected_portfolio_ids: tuple[Identifier, ...]
    expected_population_count: int = Field(ge=0)
    population_complete: bool
    membership: tuple[PooledMembershipInterval, ...]
    valuations: tuple[PooledValuation, ...]
    flows: tuple[PooledCashFlow, ...]
    flow_coverage: tuple[PooledFlowCoverage, ...]
    source_pins: tuple[PooledSourcePin, ...]
    policy: PooledPolicyBinding
    qualification: Literal["CONTROLLED_SYNTHETIC_ONLY", "OWNER_QUALIFIED_SOURCE"]
    institutional_attestation: Literal["NOT_ATTESTED", "OWNER_ATTESTED"]
    raw_source_bodies: dict[str, Any]


class PooledInvestorCashFlow(PooledContract):
    economic_date: date
    amount: ExactSourceMoney
    source_event_ids: tuple[str, ...]


class PooledMonetaryObservation(PooledContract):
    """Complete admitted projection retained atomically with its original bundle."""

    tenant_id: Identifier
    composite_id: Identifier
    source_manifest_id: Identifier
    input_manifest_digest: Identifier
    period_start: date
    period_end: date
    reporting_currency: Currency
    opening_value: ExactSourceMoney
    terminal_value: ExactSourceMoney
    portfolio_cash_flows: tuple[PooledInvestorCashFlow, ...]
    investor_cash_flows: tuple[PooledInvestorCashFlow, ...]
    per_member_controls: dict[str, dict[str, str]]
    eliminated_transfer_event_ids: tuple[str, ...]
    excluded_flow_event_ids: tuple[str, ...]
    source_bundle: PooledSourceBundle


class PooledSolverOutcome(PooledContract):
    availability: Literal["AVAILABLE", "NOT_CALCULABLE", "FALLBACK_ANALYSIS"]
    actual_method: Literal["XIRR", "MODIFIED_DIETZ", "DIETZ"]
    return_value: Decimal | None
    annualized_return: Decimal | None
    holding_period_return: Decimal | None
    units: Literal["DECIMAL_FRACTION"] = "DECIMAL_FRACTION"
    root_precision: Literal["FLOAT64"] = "FLOAT64"
    input_money_precision: Literal["EXACT_DECIMAL"] = "EXACT_DECIMAL"
    reason_codes: tuple[str, ...]
    diagnostics: dict[str, Any]
    original_solver_result: dict[str, Any]


class CompositePooledMWRAcceptedResponse(PooledContract):
    calculation_id: UUID
    status: Literal["accepted"] = "accepted"
    metric_id: Literal["POOLED_MONEY_WEIGHTED_RETURN"] = "POOLED_MONEY_WEIGHTED_RETURN"
    poll_path: str
    result_path: str
    recommended_poll_after_seconds: int = 1


class CompositePooledMWRResponse(PooledContract):
    schema_version: Literal["composite-pooled-mwr.v1"] = "composite-pooled-mwr.v1"
    calculation_id: UUID
    metric_id: Literal["POOLED_MONEY_WEIGHTED_RETURN"] = "POOLED_MONEY_WEIGHTED_RETURN"
    method: Literal["XIRR:v1"] = "XIRR:v1"
    composite_id: Identifier
    input_manifest_digest: Identifier
    calculation_engine_version: Identifier
    correction_of_calculation_id: UUID | None
    result_classification: Literal["NON_OFFICIAL_CALCULATED_ANALYSIS"] = "NON_OFFICIAL_CALCULATED_ANALYSIS"
    observation: PooledMonetaryObservation
    outcome: PooledSolverOutcome

    @model_validator(mode="after")
    def require_bound_observation(self):
        if (
            self.composite_id != self.observation.composite_id
            or self.input_manifest_digest != self.observation.input_manifest_digest
        ):
            raise ValueError("Result identity must match its retained monetary observation.")
        if self.correction_of_calculation_id == self.calculation_id:
            raise ValueError("A correction must use a new calculation identity.")
        return self
