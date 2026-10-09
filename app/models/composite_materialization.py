"""Governed commands and durable member outcomes, not caller-supplied economics."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.composite_authority import EvidenceBinding
from app.models.composite_component_costs import CompositeGrossCostMember
from app.models.composite_component_model_fees import CompositeComponentMemberFee
from app.models.composite_currency_normalization import (
    CompositeFXSnapshot,
    CompositeFXVerificationReceipt,
)
from app.models.composite_external_facts import DecimalWire
from app.models.composite_model_fees import CompositePeriodicMemberFee
from app.models.composite_scheduled_model_fees import CompositeScheduledMemberFee
from app.models.composites import CompositeMemberReturnFact, CompositeReturnView, ReportingCurrency
from app.models.portfolio_asset_evidence import PortfolioSourceAssetEvidence, PortfolioSourceAssetObservation
from app.models.twr_requests import TWRResolvedExecutionRequest

SourceReference = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
SourceDigest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
UpstreamDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MaterializationReturnView = Literal[
    CompositeReturnView.GROSS, CompositeReturnView.NET_ACTUAL, CompositeReturnView.NET_MODEL_FEE
]


class CompositeMemberCalculationReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_id: SourceReference = Field(description="Manage-owned member identity.", examples=["PORTFOLIO_A"])
    calculation_id: UUID = Field(description="Retained Performance TWR calculation, not a supplied return.")
    input_fingerprint: SourceDigest = Field(description="Pinned calculation input fingerprint.")
    calculation_hash: SourceDigest = Field(description="Pinned input and engine-version calculation hash.")


class CompositeMaterializationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(default_factory=uuid4, description="This executor attempt; reuse for exact replay.")
    materialization_id: UUID = Field(
        default_factory=uuid4, description="Stable immutable command identity across retries."
    )
    composite_id: SourceReference = Field(description="Composite governed by the pinned Manage definition.")
    definition_version: SourceReference = Field(description="Immutable Manage definition revision.")
    definition_content_hash: SourceDigest = Field(description="Expected Manage definition digest.")
    membership_revision: SourceReference = Field(description="Immutable Manage effective-membership revision.")
    membership_content_hash: SourceDigest = Field(description="Expected Manage membership digest.")
    attestation_version: SourceReference = Field(description="Immutable Manage universe attestation revision.")
    attestation_content_hash: SourceDigest = Field(description="Expected Manage universe-attestation digest.")
    source_cut_id: SourceReference = Field(description="Pinned Manage universe source cut, never a consumer date.")
    policy_version: SourceReference = Field(description="Manage membership/universe policy version.")
    period_start: date = Field(description="Inclusive fact window start.", examples=["2026-01-05"])
    period_end: date = Field(description="Inclusive fact window end.", examples=["2026-01-05"])
    reporting_currency: ReportingCurrency = Field(description="Required currency of both returns and member assets.")
    return_view: MaterializationReturnView = Field(
        default=CompositeReturnView.NET_ACTUAL,
        description="Pinned gross, actual-fee or independently admitted periodic model-fee return view.",
    )
    restatement_sequence: int = Field(ge=1, description="Immutable fact chronology; corrections use a new sequence.")
    member_calculations: list[CompositeMemberCalculationReference] = Field(
        max_length=1000,
        description="Pinned TWR references. Unavailable results wait; an omitted eligible reference blocks release.",
    )
    currency_normalization_binding: EvidenceBinding | None = Field(
        default=None,
        description="Pinned independently admitted FX source/method evidence. Absence preserves single-currency behavior.",
    )
    model_fee_binding: EvidenceBinding | None = Field(
        default=None,
        description="Immutable independently resolved periodic model-fee profile; required only for NET_MODEL_FEE.",
    )

    @model_validator(mode="after")
    def ordered_unique_members(self) -> CompositeMaterializationCommand:
        if (self.return_view == CompositeReturnView.NET_MODEL_FEE) != (self.model_fee_binding is not None):
            raise ValueError("NET_MODEL_FEE requires its own model-fee binding; other views forbid it")
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot be before period_start")
        ids = [item.portfolio_id for item in self.member_calculations]
        if len(ids) != len(set(ids)):
            raise ValueError("member_calculations must contain unique portfolio identities")
        self.member_calculations.sort(key=lambda item: item.portfolio_id)
        return self

    def immutable_payload(self) -> dict:
        excluded = {"calculation_id"}
        if self.currency_normalization_binding is None:
            excluded.add("currency_normalization_binding")
        if self.model_fee_binding is None:
            excluded.add("model_fee_binding")
        return self.model_dump(mode="json", exclude=excluded)

    @property
    def source_metric_basis(self) -> Literal["GROSS", "NET"]:
        return "NET" if self.return_view == CompositeReturnView.NET_ACTUAL else "GROSS"


class CompositeMemberOutcomeState(StrEnum):
    WAITING = "WAITING"
    READY = "READY"
    EXCLUDED = "EXCLUDED"
    BLOCKED = "BLOCKED"


class CompositeMaterializationState(StrEnum):
    WAITING = "WAITING"
    PUBLISHING = "PUBLISHING"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class CompositeCoreValuationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, description="Retained Core retrieval snapshot identifier.")
    source_identifier: str = Field(min_length=1, description="Source-owned portfolio identity.")
    request_as_of_date: date = Field(
        description="Consumer retrieval as-of date, not an invented source valuation date."
    )
    request_fingerprint: UpstreamDigest = Field(description="Immutable upstream request SHA-256 digest in bare hex.")
    response_fingerprint: UpstreamDigest = Field(description="Immutable upstream response SHA-256 digest in bare hex.")
    retrieved_at_utc: datetime = Field(description="Performance retrieval recording time, not source business time.")

    @model_validator(mode="after")
    def retrieval_time_has_timezone(self) -> "CompositeCoreValuationSnapshot":
        if self.retrieved_at_utc.tzinfo is None:
            raise ValueError("Snapshot retrieval time requires an explicit timezone")
        return self


class CompositeMemberSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["composite-member-source.v1"] = Field(
        default="composite-member-source.v1", description="Retained member evidence contract revision."
    )
    methodology: Literal["TWR"] = Field(default="TWR", description="Actual member return methodology.")
    engine_version: str = Field(min_length=1, description="Engine revision that produced the pinned return.")
    precision_mode: Literal["FLOAT64", "DECIMAL_STRICT"] = Field(description="Member calculation precision policy.")
    input_fingerprint: SourceDigest = Field(description="Pinned member calculation input digest.")
    calculation_hash: SourceDigest = Field(description="Pinned input and engine-version digest.")
    calculation_request: TWRResolvedExecutionRequest = Field(
        description="Exact retained engine request, including cash flows, fee view, dates and numerical policy."
    )
    membership_snapshot_id: SourceDigest = Field(description="Manage membership digest, distinct from Core valuations.")
    asset_evidence_fingerprint: SourceDigest = Field(description="Digest of the exact retained asset-window series.")
    period_return: Decimal = Field(
        allow_inf_nan=False, description="Verified geometrically linked period return as a decimal ratio, not percent."
    )
    source_assets: PortfolioSourceAssetEvidence = Field(description="Exact assets for the materialized member window.")
    core_snapshots: list[CompositeCoreValuationSnapshot] = Field(
        min_length=1, description="Core retrieval identities and digests retained independently of execution expiry."
    )


class CompositeNormalizedCashFlow(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    business_date: date
    placement: Literal["END_OF_DAY"]
    native_amount: Decimal
    reporting_amount: Decimal
    fixing_date: date
    rate: Decimal = Field(gt=0)


class CompositeNormalizedAssetEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_owner: Literal["lotus-performance"] = "lotus-performance"
    source_product: Literal["CompositeCurrencyNormalization"] = "CompositeCurrencyNormalization"
    reporting_currency: ReportingCurrency
    observations: list[PortfolioSourceAssetObservation] = Field(min_length=1)


class CompositeNormalizedMemberSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["composite-member-source.v3"] = "composite-member-source.v3"
    native_evidence: CompositeMemberSourceEvidence
    normalization_binding: EvidenceBinding
    verification_receipt: CompositeFXVerificationReceipt
    normalized_assets: CompositeNormalizedAssetEvidence
    normalized_cash_flows: list[CompositeNormalizedCashFlow]
    normalized_management_fees: list[CompositeNormalizedCashFlow]
    fx_snapshots: list[CompositeFXSnapshot]


class CompositeModelFeeGrossEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    gross_evidence: CompositeMemberSourceEvidence | CompositeNormalizedMemberSourceEvidence = Field(
        description="Unchanged native or FX-normalized gross receipt, including original source-money custody."
    )
    gross_receipt_digest: SourceDigest = Field(
        description="Original gross receipt digest, distinct from this model-fee receipt digest."
    )
    gross_return: Decimal = Field(
        description="Verified retained gross member return as a decimal ratio, preserving its engine precision."
    )
    model_fee_binding: EvidenceBinding = Field(
        description="Exact independently admitted fee-profile product/version/revision/digest."
    )


class CompositeModelFeeMemberEvidence(CompositeModelFeeGrossEvidence):
    contract_version: Literal["composite-member-source.v4"] = Field(
        default="composite-member-source.v4",
        description="Retained original gross evidence and governed periodic model-fee transformation revision.",
    )
    fee_entry: CompositePeriodicMemberFee = Field(
        description="Original approved member rate entry for the exact complete period."
    )


class CompositeScheduledModelFeeMemberEvidence(CompositeModelFeeGrossEvidence):
    contract_version: Literal["composite-member-source.v5"] = "composite-member-source.v5"
    fee_entry: CompositeScheduledMemberFee
    derived_period_fee_fraction: str = Field(
        strict=True,
        max_length=512,
        pattern=r"^(?:0|[1-9]\d*)(?:\.\d+)?$",
        description="Server-derived bounded Decimal wealth fraction; rederived from the original schedule on replay.",
    )

    @model_validator(mode="after")
    def valid_derived_fraction(self):
        if not Decimal(0) <= Decimal(self.derived_period_fee_fraction) < Decimal(1):
            raise ValueError("Derived model wealth fraction must be within zero inclusive to one exclusive")
        return self


class CompositeComponentModelFeeMemberEvidence(CompositeModelFeeGrossEvidence):
    contract_version: Literal["composite-member-source.v6"] = "composite-member-source.v6"
    fee_entry: CompositeComponentMemberFee
    gross_component_member: CompositeGrossCostMember
    financial_source_binding: EvidenceBinding
    total_component_fee_fraction: DecimalWire
    already_included_fee_fraction: DecimalWire
    deducted_fee_fraction: DecimalWire


class CompositeProviderMemberEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["composite-member-source.v2"] = "composite-member-source.v2"
    qualification: Literal["SYNTHETIC_TEST_ONLY"]
    definition_content_hash: SourceDigest
    profile_digest: SourceDigest
    membership_snapshot_id: SourceDigest
    return_selection_id: SourceReference
    asset_selection_id: SourceReference
    ending_asset_selection_id: SourceReference | None = None
    observation_wires: list[dict[str, Any]] = Field(max_length=3)
    internal_member_evidence: CompositeMemberSourceEvidence | None = None


class CompositeMemberMaterializationOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_id: str = Field(description="Member identity retained even when no usable economics exist.")
    state: CompositeMemberOutcomeState = Field(description="Durable member outcome, independent of job completion.")
    reason_code: str = Field(description="Bounded server-owned outcome code; no source free text.")
    retryable: bool = Field(description="Whether the same pinned evidence may become available on a later attempt.")
    inspection_attempts: int = Field(
        default=0, ge=0, description="Durable member inspection count used for fair bounded retries."
    )
    fact: CompositeMemberReturnFact | None = Field(
        default=None, description="Verified staged fact; null for missing input."
    )
    source_evidence: (
        CompositeMemberSourceEvidence
        | CompositeProviderMemberEvidence
        | CompositeNormalizedMemberSourceEvidence
        | CompositeModelFeeMemberEvidence
        | CompositeScheduledModelFeeMemberEvidence
        | CompositeComponentModelFeeMemberEvidence
        | None
    ) = Field(
        default=None, description="Pinned money, methodology and source provenance; no fabricated missing evidence."
    )

    @model_validator(mode="after")
    def fact_matches_outcome(self) -> CompositeMemberMaterializationOutcome:
        if (self.state == CompositeMemberOutcomeState.READY) != (self.fact is not None):
            raise ValueError("Only READY outcomes contain financial facts")
        if self.fact is not None and self.fact.portfolio_id != self.portfolio_id:
            raise ValueError("Outcome and fact portfolio identities differ")
        if (self.state == CompositeMemberOutcomeState.READY) != (self.source_evidence is not None):
            raise ValueError("Only READY outcomes retain verified source evidence")
        return self


class CompositeMaterializationProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    materialization_id: UUID = Field(description="Immutable command identity.")
    composite_id: str = Field(description="Governed composite identity.")
    state: CompositeMaterializationState = Field(description="Release state; only COMPLETE admits calculation.")
    revision: int = Field(ge=0, description="Optimistic durable progress revision for restart/concurrent workers.")
    source_cut_id: str = Field(description="Pinned Manage source cut.")
    expected_count: int = Field(ge=0, description="Attested universe count, not a fact-row count.")
    ready_count: int = Field(ge=0, description="Verified eligible member fact count.")
    excluded_count: int = Field(ge=0, description="Explicitly source-excluded members.")
    blocked_count: int = Field(ge=0, description="Members refused because their pinned evidence is not supportable.")
    waiting_count: int = Field(ge=0, description="Members awaiting pinned evidence.")
    retryable: bool = Field(
        description="Whether another executor attempt can make progress without changing this command."
    )
    reason_code: str | None = Field(
        default=None, description="Bounded release refusal; null only after complete release."
    )
    restatement_sequence: int = Field(ge=1, description="Immutable fact chronology.")
    reporting_currency: ReportingCurrency = Field(description="Pinned applied return and asset currency.")
    returned_count: int = Field(ge=0, description="Member outcomes on this inspection page.")
    next_offset: int | None = Field(description="Next stable sorted-member page, or null after exhaustion.")
    members: list[CompositeMemberMaterializationOutcome] = Field(
        description="All outcome types; missing members are not omitted."
    )


class CompositeMaterializationAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_id: UUID = Field(description="Executor attempt identity.")
    materialization_id: UUID = Field(description="Stable materialization identity.")
    poll_path: str = Field(description="Supported execution polling path.")
    result_path: str = Field(description="Supported durable materialization inspection path.")
    contract_version: Literal["v1"] = Field(default="v1", description="Governed command contract revision.")
