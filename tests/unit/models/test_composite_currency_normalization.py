"""Reject incompatible source wires without treating schema validity as authority."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.models.composite_authority import EvidenceBinding, authority_digest
from app.models.composite_currency_normalization import CompositeFXNormalizationSource
from app.ports.composite_currency_normalization import (
    CompositeFXResolutionRequest,
    CompositeFXVerificationRequest,
    composite_fx_receipt_verifier,
    composite_fx_source_resolver,
)
from app.ports.composite_external_evidence import UnavailableCompositeEvidence
from tests.composite_currency_normalization_helpers import normalization_wire


def test_source_money_and_reference_currency_remain_distinct_without_qualified_default():
    source = CompositeFXNormalizationSource.model_validate(normalization_wire())
    assert source.members[0].portfolio_reference_currency == "GBP"
    assert source.members[0].source_money_currency == "EUR"
    assert source.reporting_currency == "USD"
    request = CompositeFXResolutionRequest(
        tenant_id=source.tenant_id,
        composite_id=source.composite_id,
        binding=EvidenceBinding(
            product_name=source.product_name,
            product_version=source.product_version,
            revision=source.revision,
            digest=authority_digest(source.model_dump()),
        ),
        definition_content_hash=source.definition_content_hash,
        membership_content_hash=source.membership_content_hash,
        attestation_content_hash=source.attestation_content_hash,
        source_cut_id=source.source_cut_id,
        period_start=source.period_start,
        period_end=source.period_end,
        reporting_currency=source.reporting_currency,
        return_view=source.return_view,
        expected_members=tuple(member.member_id for member in source.members),
    )
    verification = CompositeFXVerificationRequest(
        resolution=request,
        source=source,
        source_digest=request.binding.digest,
        method_digest=source.method_binding.digest,
    )
    assert isinstance(composite_fx_source_resolver().resolve(request), UnavailableCompositeEvidence)
    assert isinstance(composite_fx_receipt_verifier().verify(verification), UnavailableCompositeEvidence)


@pytest.mark.parametrize("rate", ["0", "-1", "NaN", "Infinity", "1e3", 1.3])
def test_source_fixing_refuses_invalid_or_lossy_rates(rate):
    wire = normalization_wire()
    wire["members"][0]["fixings"][0]["rate"] = rate
    with pytest.raises(ValidationError):
        CompositeFXNormalizationSource.model_validate(wire)


@pytest.mark.parametrize(
    "field,value",
    [
        ("quote_direction", "SOURCE_UNITS_PER_REPORTING_UNIT"),
        ("reporting_currency", "EUR"),
        ("source_currency", "GBP"),
        ("source_cut_id", "stale-cut"),
        ("fixing_date", "2026-02-30"),
        ("provenance", "TRIANGULATED"),
    ],
)
def test_source_fixing_refuses_ambiguous_scope_or_unsupported_provenance(field, value):
    wire = normalization_wire()
    wire["members"][0]["fixings"][0][field] = value
    with pytest.raises(ValidationError):
        CompositeFXNormalizationSource.model_validate(wire)


def test_source_refuses_duplicate_fixing_instead_of_selecting_last_revision():
    wire = normalization_wire()
    wire["members"][0]["fixings"].insert(1, deepcopy(wire["members"][0]["fixings"][0]))
    wire["members"][0]["fixings"][1]["source_revision"] = "corrected2"
    with pytest.raises(ValidationError, match="unique ordered dates"):
        CompositeFXNormalizationSource.model_validate(wire)


@pytest.mark.parametrize(
    "field,value", [("mode", "HEDGED"), ("calendar", "BUSINESS"), ("supported_flow_placement", "BEGINNING_OF_DAY")]
)
def test_method_refuses_undefined_hedging_calendar_or_flow_semantics(field, value):
    wire = normalization_wire()
    wire["method"][field] = value
    wire["method_binding"]["digest"] = authority_digest(wire["method"])
    with pytest.raises(ValidationError):
        CompositeFXNormalizationSource.model_validate(wire)


def test_method_binding_cannot_relabel_changed_economic_date_fixing():
    wire = normalization_wire()
    wire["method_binding"]["digest"] = "sha256:" + "1" * 64
    with pytest.raises(ValidationError, match="exact retained wire"):
        CompositeFXNormalizationSource.model_validate(wire)


@pytest.mark.parametrize("observed", [None, "2026-01-04T21:00:00", "2026-01-04T21:00:01Z", "2026-01-04T20:58:59Z"])
def test_original_observation_time_is_required_and_prevents_lookahead_or_stale_fixings(observed):
    wire = normalization_wire()
    if observed is None:
        del wire["members"][0]["fixings"][0]["observed_at"]
    else:
        wire["members"][0]["fixings"][0]["observed_at"] = observed
    with pytest.raises(ValidationError):
        CompositeFXNormalizationSource.model_validate(wire)


def test_original_observation_time_retains_timezone_spelling_under_exact_source_digest():
    wire = normalization_wire()
    original_hash = authority_digest(wire)
    wire["members"][0]["fixings"][0]["observed_at"] = "2026-01-04T22:00:00+01:00"
    source = CompositeFXNormalizationSource.model_validate(wire)
    assert source.members[0].fixings[0].observed_at == "2026-01-04T22:00:00+01:00"
    assert authority_digest(wire) != original_hash


def test_late_revision_is_representable_only_after_its_actual_source_availability():
    wire = normalization_wire()
    fixing = wire["members"][0]["fixings"][0]
    fixing.update({"source_revision": "correction2", "revision_available_at": "2026-01-06T00:00:00Z"})
    source = CompositeFXNormalizationSource.model_validate(wire)
    assert source.members[0].fixings[0].observed_at == "2026-01-04T21:00:00Z"
    wire["source_as_of_cut"] = "2026-01-05T22:00:00Z"
    with pytest.raises(ValidationError, match="unavailable at the pinned source as-of cut"):
        CompositeFXNormalizationSource.model_validate(wire)


@pytest.mark.parametrize("available", [None, "2026-01-04T21:01:00", "2026-01-04T20:59:00Z"])
def test_revision_availability_is_required_and_cannot_be_inferred_from_original_observation(available):
    wire = normalization_wire()
    if available is None:
        del wire["members"][0]["fixings"][0]["revision_available_at"]
    else:
        wire["members"][0]["fixings"][0]["revision_available_at"] = available
    with pytest.raises(ValidationError):
        CompositeFXNormalizationSource.model_validate(wire)


@pytest.mark.parametrize(
    "fault, message",
    [
        ("inverted-method", "method interval is inverted"),
        ("empty-direct", "Direct conversion requires fixing evidence"),
        ("duplicate-member", "members must be sorted and unique"),
        ("inverted-period", "period is inverted"),
        ("outside-method", "does not cover"),
        ("identity-pair", "Identity conversion must match"),
    ],
)
def test_currency_source_refuses_incoherent_method_population_and_window(fault, message):
    wire = normalization_wire()
    if fault == "inverted-method":
        wire["method"].update(effective_from="2026-01-06", effective_to="2026-01-05")
        wire["method_binding"]["digest"] = authority_digest(wire["method"])
    elif fault == "empty-direct":
        wire["members"][0]["fixings"] = []
    elif fault == "duplicate-member":
        wire["members"].append(deepcopy(wire["members"][0]))
    elif fault == "inverted-period":
        wire["period_start"] = "2026-01-06"
    elif fault == "outside-method":
        wire["period_end"] = "2026-02-01"
    else:
        wire["members"][0].update(conversion_kind="IDENTITY", fixings=[])
    with pytest.raises(ValidationError, match=message):
        CompositeFXNormalizationSource.model_validate(wire)
