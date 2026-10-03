"""Governed commands and durable member outcomes, not caller-supplied economics."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.composites import CompositeMemberReturnFact, CompositeReturnView, ReportingCurrency
from app.models.portfolio_asset_evidence import PortfolioSourceAssetEvidence
from app.models.twr_requests import TWRResolvedExecutionRequest

SourceReference = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
SourceDigest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
UpstreamDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MaterializationReturnView = Literal[CompositeReturnView.GROSS, CompositeReturnView.NET_ACTUAL]


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
        description="Pinned actual-fee or gross TWR view. Model-fee materialization is not supported.",
    )
    restatement_sequence: int = Field(ge=1, description="Immutable fact chronology; corrections use a new sequence.")
    member_calculations: list[CompositeMemberCalculationReference] = Field(
        max_length=1000,
        description="Pinned TWR references. Unavailable results wait; an omitted eligible reference blocks release.",
    )

    @model_validator(mode="after")
    def ordered_unique_members(self) -> CompositeMaterializationCommand:
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot be before period_start")
        ids = [item.portfolio_id for item in self.member_calculations]
        if len(ids) != len(set(ids)):
            raise ValueError("member_calculations must contain unique portfolio identities")
        self.member_calculations.sort(key=lambda item: item.portfolio_id)
        return self

    def immutable_payload(self) -> dict:
        return self.model_dump(mode="json", exclude={"calculation_id"})


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
    source_evidence: CompositeMemberSourceEvidence | None = Field(
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
