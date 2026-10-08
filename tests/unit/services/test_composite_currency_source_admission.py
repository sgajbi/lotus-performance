"""Source scope and independent verification are necessary even for controlled FX."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.models.composite_authority import EvidenceBinding, authority_digest
from app.ports.composite_currency_normalization import (
    CompositeFXResolutionRequest,
)
from app.services.composite_materialization.currency_source_admission import (
    admit_composite_fx_source,
    require_fx_normalization_route,
)
from core.errors import APIUnprocessableEntityError
from tests.composite_currency_normalization_helpers import normalization_wire
from tests.composite_currency_normalization_helpers import synthetic_fx_verification as _verified


@pytest.mark.parametrize("mode", ["INTERNAL", "EXTERNAL", "HYBRID"])
def test_aggregate_currency_method_is_unavailable_but_internal_route_is_supported(mode):
    from app.models.composite_authority import ManageCompositeDefinitionV2
    from tests.composite_authority_helpers import internal_day_packet

    definition = ManageCompositeDefinitionV2.model_validate(internal_day_packet()["definition"])
    profile = definition.source_authority.model_copy(
        update={"payload": definition.source_authority.payload.model_copy(update={"mode": mode})}
    )
    selected = definition.model_copy(update={"source_authority": profile})
    if mode == "INTERNAL":
        require_fx_normalization_route(selected)
    else:
        with pytest.raises(APIUnprocessableEntityError) as refused:
            require_fx_normalization_route(selected)
        assert refused.value.error_code == "COMPOSITE_FX_AGGREGATE_METHOD_UNAVAILABLE"


def _request(wire):
    return CompositeFXResolutionRequest(
        tenant_id="tenant-a",
        composite_id="COMPOSITE",
        binding=EvidenceBinding(
            product_name="CompositeFXNormalizationSource",
            product_version="v1",
            revision="normalization1",
            digest=authority_digest(wire),
        ),
        definition_content_hash=wire["definition_content_hash"],
        membership_content_hash=wire["membership_content_hash"],
        attestation_content_hash=wire["attestation_content_hash"],
        source_cut_id="cut1",
        period_start="2026-01-05",
        period_end="2026-01-05",
        reporting_currency="USD",
        return_view="GROSS",
        expected_members=("A",),
    )


def _ports(wire, verify=_verified):
    return {"resolver": SimpleNamespace(resolve=lambda request: wire), "verifier": SimpleNamespace(verify=verify)}


def test_matching_source_is_verified_and_snapshotted_before_any_money_conversion():
    wire = normalization_wire()
    admitted = admit_composite_fx_source(_request(wire), **_ports(wire))
    assert admitted.verification_receipt.qualification == "SYNTHETIC_TEST_ONLY"
    assert admitted.verification_receipt.official_activation == "UNAVAILABLE"
    wire["members"][0]["fixings"][0]["rate"] = "99"
    assert admitted.source_wire["members"][0]["fixings"][0]["rate"] == "1.3"
    assert admitted.source.members[0].fixings[0].rate == "1.3"


def test_decoded_source_does_not_supply_independent_verification():
    wire = normalization_wire()
    with pytest.raises(APIUnprocessableEntityError) as error:
        admit_composite_fx_source(_request(wire), resolver=_ports(wire)["resolver"])
    assert error.value.error_code == "COMPOSITE_FX_INDEPENDENT_VERIFICATION_UNAVAILABLE"


def test_default_source_is_unavailable_even_with_a_valid_pinned_binding():
    with pytest.raises(APIUnprocessableEntityError) as error:
        admit_composite_fx_source(_request(normalization_wire()))
    assert error.value.error_code == "COMPOSITE_FX_SOURCE_UNAVAILABLE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "tenant-b"),
        ("composite_id", "OTHER"),
        ("source_cut_id", "cut2"),
        ("period_start", "2026-01-04"),
        ("period_end", "2026-01-06"),
        ("reporting_currency", "EUR"),
        ("return_view", "NET_ACTUAL"),
        ("expected_members", ("A", "B")),
        ("definition_content_hash", "sha256:" + "1" * 64),
        ("membership_content_hash", "sha256:" + "2" * 64),
        ("attestation_content_hash", "sha256:" + "3" * 64),
    ],
)
def test_bound_source_cannot_cross_tenant_cut_window_or_full_population(field, value):
    wire = normalization_wire()
    with pytest.raises(APIUnprocessableEntityError) as error:
        admit_composite_fx_source(replace(_request(wire), **{field: value}), **_ports(wire))
    assert error.value.error_code == "COMPOSITE_FX_SOURCE_SCOPE_MISMATCH"


def test_changed_fixing_cannot_replay_under_an_original_digest():
    wire = normalization_wire()
    original = _request(wire)
    wire["members"][0]["fixings"][0]["rate"] = "1.31"
    with pytest.raises(APIUnprocessableEntityError) as error:
        admit_composite_fx_source(original, **_ports(wire))
    assert error.value.error_code == "COMPOSITE_FX_SOURCE_DIGEST_MISMATCH"


def test_boolean_verification_is_not_a_bound_receipt():
    wire = normalization_wire()
    with pytest.raises(APIUnprocessableEntityError) as error:
        admit_composite_fx_source(_request(wire), **_ports(wire, verify=lambda request: True))
    assert error.value.error_code == "COMPOSITE_FX_INDEPENDENT_VERIFICATION_UNAVAILABLE"


@pytest.mark.parametrize("fault", ["expectation", "issuer", "official", "receipt_type"])
def test_verifier_cannot_return_mismatched_or_promoted_evidence(fault):
    wire = normalization_wire()

    def verify(request):
        result = _verified(request)
        if fault == "expectation":
            return replace(
                result,
                expectation=replace(result.expectation, request=replace(request, source_digest="sha256:" + "8" * 64)),
            )
        if fault == "issuer":
            return replace(result, expectation=replace(result.expectation, issuer_id="unrelated-issuer"))
        if fault == "receipt_type":
            return replace(result, verification_receipt={"verified": True})
        return replace(
            result,
            verification_receipt=result.verification_receipt.model_copy(update={"official_activation": "AVAILABLE"}),
        )

    with pytest.raises(APIUnprocessableEntityError):
        admit_composite_fx_source(_request(wire), **_ports(wire, verify=verify))


def test_retained_wire_rechecks_independent_verification_without_source_refetch():
    wire = normalization_wire()
    called = []

    def verify(request):
        called.append(request)
        return _verified(request)

    admitted = admit_composite_fx_source(_request(wire), retained_wire=wire, verifier=SimpleNamespace(verify=verify))
    assert len(called) == 1
    assert admitted.source_wire == wire
    with pytest.raises(APIUnprocessableEntityError) as error:
        admit_composite_fx_source(_request(wire), retained_wire=admitted.source_wire)
    assert error.value.error_code == "COMPOSITE_FX_INDEPENDENT_VERIFICATION_UNAVAILABLE"
