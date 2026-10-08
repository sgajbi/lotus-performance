"""Versioned source custody for normalization; decoding never grants authority."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.models.composite_authority import (
    AuthorityWire,
    BusinessDate,
    Digest,
    EvidenceBinding,
    Identifier,
    authority_digest,
)
from app.models.composite_external_facts import DecimalWire

Currency = Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}$")]
BareDigest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


class CompositeFXRetrievedWire(AuthorityWire):
    request_wire: dict
    response_wire: dict


class CompositeFXSnapshot(AuthorityWire):
    snapshot_id: BareDigest
    upstream_endpoint: Literal["fx_rates"]
    source_identifier: Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}/[A-Z]{3}$")]
    as_of_date: BusinessDate
    request_fingerprint: BareDigest
    response_fingerprint: BareDigest
    retrieval_status: Literal["200"]
    paging_metadata: dict
    created_at_utc: str


def _aware_source_time(value, message):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(message)
    return parsed


class CompositeFXFixing(AuthorityWire):
    fixing_date: BusinessDate
    source_currency: Currency
    reporting_currency: Currency
    quote_direction: Literal["REPORTING_UNITS_PER_SOURCE_UNIT"]
    rate: DecimalWire
    observed_at: Annotated[str, Field(strict=True, max_length=40)]
    revision_available_at: Annotated[str, Field(strict=True, max_length=40)]
    provider_id: Identifier
    source_product: Identifier
    source_revision: Identifier
    source_cut_id: Identifier
    source_watermark: Identifier
    source_content_hash: Digest
    retrieval_response_fingerprint: BareDigest | None = None
    fixing_kind: Literal["EOD"]
    calendar_binding: EvidenceBinding
    provenance: Literal["DIRECT"]

    @model_validator(mode="after")
    def positive_dated_pair(self):
        date.fromisoformat(self.fixing_date)
        observed = _aware_source_time(self.observed_at, "Original FX observation time requires an explicit timezone")
        available = _aware_source_time(
            self.revision_available_at,
            "FX revision availability requires an aware source time after original observation",
        )
        if available < observed:
            raise ValueError("FX revision availability requires an aware source time after original observation")
        if Decimal(self.rate) <= 0:
            raise ValueError("A fixing must be strictly positive")
        if self.source_currency == self.reporting_currency:
            raise ValueError("Same-currency money uses explicit identity conversion, not an invented fixing")
        return self


class CompositeFXMethod(AuthorityWire):
    product_name: Literal["CompositeFXMethod"]
    product_version: Literal["v1"]
    revision: Identifier
    effective_from: BusinessDate
    effective_to: BusinessDate
    mode: Literal["UNHEDGED"]
    return_method: Literal["EXISTING_DAILY_MEMBER_ENGINE"]
    calendar: Literal["NATURAL_DAILY"]
    calendar_binding: EvidenceBinding
    fixing_timezone: Literal["UTC"]
    fixing_time_utc: Annotated[str, Field(strict=True, pattern=r"^\d{2}:\d{2}:\d{2}$")]
    maximum_observation_age_seconds: Annotated[int, Field(strict=True, ge=0, le=86400)]
    return_fixing: Literal["EXACT_PRIOR_AND_CURRENT_EOD"]
    beginning_asset_fixing: Literal["PRIOR_DAY_EOD"]
    ending_asset_fixing: Literal["VALUATION_DAY_EOD"]
    flow_fixing: Literal["ECONOMIC_DAY_EOD"]
    supported_flow_placement: Literal["END_OF_DAY"]
    monetary_precision: Literal["DECIMAL_STRICT_NO_INTERMEDIATE_ROUNDING"]

    @model_validator(mode="after")
    def ordered_effective_window(self):
        time.fromisoformat(self.fixing_time_utc)
        if date.fromisoformat(self.effective_to) < date.fromisoformat(self.effective_from):
            raise ValueError("Normalization method interval is inverted")
        return self


class CompositeFXMemberSource(AuthorityWire):
    member_id: Identifier
    portfolio_reference_currency: Currency
    source_money_currency: Currency
    input_fingerprint: Digest
    calculation_hash: Digest
    conversion_kind: Literal["DIRECT", "IDENTITY"]
    fixings: list[CompositeFXFixing] = Field(max_length=4096)
    retrieval_wires: list[CompositeFXRetrievedWire] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def unique_fixing_dates(self):
        dates = [fixing.fixing_date for fixing in self.fixings]
        if dates != sorted(set(dates)):
            raise ValueError("Fixings must have unique ordered dates; duplicate-last selection is unavailable")
        if (self.conversion_kind == "DIRECT") != bool(self.fixings):
            raise ValueError("Direct conversion requires fixing evidence; identity conversion forbids it")
        return self


class CompositeFXNormalizationSource(AuthorityWire):
    product_name: Literal["CompositeFXNormalizationSource"]
    product_version: Literal["v1"]
    tenant_id: Identifier
    composite_id: Identifier
    revision: Identifier
    definition_content_hash: Digest
    membership_content_hash: Digest
    attestation_content_hash: Digest
    source_cut_id: Identifier
    source_as_of_cut: Annotated[str, Field(strict=True, max_length=40)]
    period_start: BusinessDate
    period_end: BusinessDate
    composite_native_currency: Currency
    reporting_currency: Currency
    return_view: Literal["GROSS", "NET_ACTUAL"]
    method: CompositeFXMethod
    method_binding: EvidenceBinding
    members: list[CompositeFXMemberSource] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def exact_member_and_currency_scope(self):
        start, end = date.fromisoformat(self.period_start), date.fromisoformat(self.period_end)
        source_cut = _aware_source_time(self.source_as_of_cut, "FX source as-of cut requires an explicit timezone")
        self._require_method_scope(start, end)
        ids = [member.member_id for member in self.members]
        if ids != sorted(set(ids)):
            raise ValueError("Normalization members must be sorted and unique")
        for member in self.members:
            self._require_member_scope(member, source_cut)
        return self

    def _require_method_scope(self, start, end):
        if end < start:
            raise ValueError("Normalization period is inverted")
        if (
            not date.fromisoformat(self.method.effective_from)
            <= start
            <= end
            <= date.fromisoformat(self.method.effective_to)
        ):
            raise ValueError("Normalization method does not cover the requested period")
        if (self.method_binding.product_name, self.method_binding.revision, self.method_binding.digest) != (
            self.method.product_name,
            self.method.revision,
            authority_digest(self.method.model_dump()),
        ):
            raise ValueError("Normalization method binding does not identify its exact retained wire")

    def _require_member_scope(self, member, source_cut):
        if (member.source_money_currency == self.reporting_currency) != (member.conversion_kind == "IDENTITY"):
            raise ValueError("Identity conversion must match source money and reporting currency")
        for fixing in member.fixings:
            self._require_fixing_scope(member, fixing, source_cut)

    def _require_fixing_scope(self, member, fixing, source_cut):
        fixing_instant = datetime.combine(
            date.fromisoformat(fixing.fixing_date), time.fromisoformat(self.method.fixing_time_utc), tzinfo=timezone.utc
        )
        observed = datetime.fromisoformat(fixing.observed_at.replace("Z", "+00:00"))
        available = datetime.fromisoformat(fixing.revision_available_at.replace("Z", "+00:00"))
        if available > source_cut:
            raise ValueError("FX revision was unavailable at the pinned source as-of cut")
        if (
            not fixing_instant - timedelta(seconds=self.method.maximum_observation_age_seconds)
            <= observed
            <= fixing_instant
        ):
            raise ValueError("Original FX observation is stale or later than the admitted fixing instant")
        if (fixing.source_currency, fixing.reporting_currency, fixing.source_cut_id, fixing.calendar_binding) != (
            member.source_money_currency,
            self.reporting_currency,
            self.source_cut_id,
            self.method.calendar_binding,
        ):
            raise ValueError("Fixing pair, source cut or calendar conflicts with the pinned normalization")


class CompositeFXVerificationReceipt(AuthorityWire):
    """Bounded test verification wire; institutionally qualified receipts are unsupported."""

    product_name: Literal["CompositeFXVerificationReceipt"]
    product_version: Literal["v1"]
    qualification: Literal["SYNTHETIC_TEST_ONLY"]
    official_activation: Literal["UNAVAILABLE"]
    tenant_id: Identifier
    composite_id: Identifier
    verifier_id: Identifier
    issuer_id: Identifier
    artifact_revision: Identifier
    artifact_digest: Digest
    source_digest: Digest
    method_digest: Digest
    request_digest: Digest
    content_hash: Digest

    @model_validator(mode="after")
    def canonical_receipt_digest(self):
        if authority_digest(self.model_dump(exclude={"content_hash"})) != self.content_hash:
            raise ValueError("FX verification receipt digest differs from its exact wire")
        return self
