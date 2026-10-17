"""Closed current-issued annual declaration; no financial or publication authority."""

import base64
import hashlib
from datetime import date, datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from app.models.composite_authority import (
    AuthorityProvider,
    BusinessDate,
    EvidenceBinding,
    Identifier,
    Instant,
    MemberIdentity,
    decode_authority_json,
)
from app.models.composite_eligibility_evidence import EligibilityWire, HashedEligibilityWire, _require
from app.models.composite_historical_subject_evidence import HistoricalPolicyReference


class ControlledYearScope(EligibilityWire):
    tenant_id: Identifier
    composite_id: Identifier
    definition_version: Identifier
    strategy_code: Identifier
    reporting_currency: str = Field(strict=True, pattern=r"^[A-Z]{3}$")
    eligibility_policy_version: Identifier


class ControlledYearAuthorityRule(EligibilityWire):
    rule_id: Identifier
    fact: Literal["BEGINNING_ASSETS", "ENDING_ASSETS", "MEMBER_RETURN"]
    member_ids: list[Identifier] = Field(min_length=1, max_length=1000)
    effective_from: BusinessDate
    effective_to: BusinessDate
    provider_id: Identifier
    economic_authority: Identifier
    publisher_service: Identifier
    source_product: Identifier
    source_contract_version: Identifier
    source_enrollment_ref: Identifier
    method_profile_binding: EvidenceBinding | None

    @model_validator(mode="after")
    def rule_shape(self) -> Self:
        _require(self.member_ids == sorted(set(self.member_ids)), "COMPOSITE_YEAR_RULE_MEMBERS_NONCANONICAL")
        _require(self.effective_from <= self.effective_to, "COMPOSITE_YEAR_RULE_WINDOW_MISMATCH")
        owner = "lotus-performance" if self.fact == "MEMBER_RETURN" else "lotus-core"
        _require(
            self.provider_id == self.economic_authority == self.publisher_service == owner,
            "COMPOSITE_YEAR_RULE_OWNER_MISMATCH",
        )
        _require(
            (self.method_profile_binding is not None) == (self.fact == "MEMBER_RETURN"),
            "COMPOSITE_YEAR_RULE_METHOD_MISMATCH",
        )
        return self


class ControlledYearMonthSelection(EligibilityWire):
    month: str = Field(strict=True, pattern=r"^\d{4}-\d{2}$")
    candidate_registry_binding: EvidenceBinding
    monthly_policy_reference: HistoricalPolicyReference
    source_enrollment_ref: Identifier

    @model_validator(mode="after")
    def selected_sources(self) -> Self:
        _require(
            self.candidate_registry_binding.product_name == "PortfolioHistoricalRegistry",
            "COMPOSITE_YEAR_REGISTRY_BINDING_MISMATCH",
        )
        _require(
            self.monthly_policy_reference.signing_contract == "CONTROLLED_SYNTHETIC_POLICY_V1",
            "COMPOSITE_YEAR_POLICY_REFERENCE_MISMATCH",
        )
        return self


class CompositeControlledYearBasis(EligibilityWire):
    format: Literal["CONTROLLED_SYNTHETIC_YEAR_BASIS_V1"]
    product_name: Literal["CompositeControlledYearBasis"]
    product_version: Literal["v1"]
    purpose: Literal["COMPOSITE_CONTROLLED_YEAR_BASIS"]
    posture: Literal["SYNTHETIC_NON_CERTIFYING"]
    signature_semantics: Literal["SCENARIO_DECLARATION_AT_ACTUAL_ISSUANCE"]
    issuer_id: Identifier
    artifact_id: Identifier
    revision: Identifier
    signer_principal_id: Identifier
    actual_issued_at: Instant
    scenario_proposed_by: Identifier
    scenario_proposed_at: Instant
    scenario_approved_by: Identifier
    scenario_approved_at: Instant
    scope: ControlledYearScope
    year: int = Field(strict=True, ge=1900, le=9998)
    effective_from: BusinessDate
    effective_to: BusinessDate
    profile_id: Identifier
    profile_revision: Identifier
    mode: Literal["INTERNAL"]
    member_identities: list[MemberIdentity] = Field(min_length=1, max_length=1000)
    providers: list[AuthorityProvider] = Field(min_length=2, max_length=16)
    return_method_binding: EvidenceBinding
    authority_rules: list[ControlledYearAuthorityRule] = Field(min_length=2, max_length=256)
    months: list[ControlledYearMonthSelection] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def annual_declaration(self) -> Self:
        first, last = f"{self.year:04d}-01-01", f"{self.year:04d}-12-31"
        _require((self.effective_from, self.effective_to) == (first, last), "COMPOSITE_YEAR_WINDOW_MISMATCH")
        instants = (self.scenario_proposed_at, self.scenario_approved_at, self.actual_issued_at)
        for instant in instants:
            datetime.strptime(instant, "%Y-%m-%dT%H:%M:%S.%fZ")
        _require(
            self.scenario_proposed_at <= self.scenario_approved_at < first
            and self.actual_issued_at >= self.scenario_approved_at
            and self.actual_issued_at[:10] > last,
            "COMPOSITE_YEAR_CLOCK_MISMATCH",
        )
        _require(
            self.scenario_proposed_by != self.scenario_approved_by, "COMPOSITE_ELIGIBILITY_SELF_APPROVAL_FORBIDDEN"
        )
        _require(
            [item.month for item in self.months] == [f"{self.year:04d}-{month:02d}" for month in range(1, 13)],
            "COMPOSITE_YEAR_MONTH_VECTOR_MISMATCH",
        )
        _annual_collections(self)
        return self


def _annual_collections(basis: CompositeControlledYearBasis) -> None:
    ids = [item.member_id for item in basis.member_identities]
    _require(ids == sorted(set(ids)), "COMPOSITE_YEAR_MEMBER_MAP_MISMATCH")
    _require(
        all(
            item.identity_kind == "CORE_PORTFOLIO" and item.provider_id == "lotus-core"
            for item in basis.member_identities
        ),
        "COMPOSITE_YEAR_MEMBER_KIND_MISMATCH",
    )
    providers = [(item.provider_id, item.source_kind) for item in basis.providers]
    _require(
        providers == [("lotus-core", "LOTUS_CORE"), ("lotus-performance", "LOTUS_PERFORMANCE")],
        "COMPOSITE_YEAR_PROVIDER_MISMATCH",
    )
    rule_ids = [item.rule_id for item in basis.authority_rules]
    _require(rule_ids == sorted(set(rule_ids)), "COMPOSITE_YEAR_RULES_NONCANONICAL")
    _annual_rule_scopes(basis, ids)
    for member_id in ids:
        for fact in ("MEMBER_RETURN", "BEGINNING_ASSETS", "ENDING_ASSETS"):
            _nonoverlapping_rules(basis, member_id, fact)


def _annual_rule_scopes(basis, ids) -> None:
    for rule in basis.authority_rules:
        _require(set(rule.member_ids) <= set(ids), "COMPOSITE_YEAR_MEMBER_MAP_MISMATCH")
        _require(
            basis.effective_from <= rule.effective_from <= rule.effective_to <= basis.effective_to,
            "COMPOSITE_YEAR_RULE_WINDOW_MISMATCH",
        )
        if rule.fact == "MEMBER_RETURN":
            _require(rule.method_profile_binding == basis.return_method_binding, "COMPOSITE_YEAR_RULE_METHOD_MISMATCH")


def _nonoverlapping_rules(basis, member_id, fact) -> None:
    windows = sorted(
        (item for item in basis.authority_rules if member_id in item.member_ids and item.fact == fact),
        key=lambda item: item.effective_from,
    )
    _require(
        all(previous.effective_to < current.effective_from for previous, current in zip(windows, windows[1:])),
        "COMPOSITE_YEAR_RULE_OVERLAP",
    )


class ControlledYearBasisMapping(HashedEligibilityWire):
    reference: HistoricalPolicyReference
    raw_original_base64: str = Field(strict=True, min_length=4, max_length=2800000)
    original_credential: str = Field(strict=True, min_length=1, max_length=16384)
    basis: CompositeControlledYearBasis

    @model_validator(mode="after")
    def original_bytes(self) -> Self:
        raw = base64.b64decode(self.raw_original_base64, validate=True)
        signature = base64.b64decode(self.original_credential, validate=True)
        _require(
            0 < len(raw) <= 2000000 and base64.b64encode(raw).decode() == self.raw_original_base64,
            "COMPOSITE_YEAR_RAW_INVALID",
        )
        _require(
            len(signature) == 64 and base64.b64encode(signature).decode() == self.original_credential,
            "COMPOSITE_YEAR_SOURCE_CREDENTIAL_INVALID",
        )
        _require(
            "sha256:" + hashlib.sha256(raw).hexdigest() == self.reference.raw_digest,
            "COMPOSITE_YEAR_RAW_MISMATCH",
        )
        _require(
            CompositeControlledYearBasis.model_validate(decode_authority_json(raw.decode("utf-8"))) == self.basis,
            "COMPOSITE_YEAR_RAW_MISMATCH",
        )
        _require(
            (
                self.reference.issuer_id,
                self.reference.artifact_id,
                self.reference.revision,
                self.reference.signing_contract,
            )
            == (
                self.basis.issuer_id,
                self.basis.artifact_id,
                self.basis.revision,
                "CONTROLLED_SYNTHETIC_YEAR_BASIS_V1",
            ),
            "COMPOSITE_YEAR_REFERENCE_MISMATCH",
        )
        return self


def year_rules_for_window(basis, member_id: str, fact: str, first: str, last: str) -> list[ControlledYearAuthorityRule]:
    rules = [
        rule
        for rule in basis.authority_rules
        if rule.fact == fact
        and member_id in rule.member_ids
        and rule.effective_from <= last
        and rule.effective_to >= first
    ]
    rules.sort(key=lambda rule: rule.effective_from)
    _require(bool(rules), "COMPOSITE_YEAR_RULE_COVERAGE_MISMATCH")
    _require(
        rules[0].effective_from <= first <= last <= rules[-1].effective_to, "COMPOSITE_YEAR_RULE_COVERAGE_MISMATCH"
    )
    for previous, current in zip(rules, rules[1:]):
        _require(
            (date.fromisoformat(current.effective_from) - date.fromisoformat(previous.effective_to)).days == 1,
            "COMPOSITE_YEAR_RULE_COVERAGE_MISMATCH",
        )
    date.fromisoformat(first)
    date.fromisoformat(last)
    return rules


def required_year_facts(basis, member_id: str, first: str, last: str) -> list[str]:
    facts = ["MEMBER_RETURN", "BEGINNING_ASSETS"]
    if any(
        rule.fact == "ENDING_ASSETS"
        and member_id in rule.member_ids
        and rule.effective_from <= last
        and rule.effective_to >= first
        for rule in basis.authority_rules
    ):
        facts.append("ENDING_ASSETS")
    return facts
