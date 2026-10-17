"""Normal worker/owned SQLite custody; no invented native financial success."""

import base64
import json
from datetime import date
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource
from app.core.config import get_settings
from app.models.composite_controlled_annual_authority import ControlledAnnualDefinitionV4
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from app.ports import composite_controlled_annual_evidence as year_ports
from app.ports import composite_external_evidence as evidence_ports
from app.services.composite_materialization.application import _default_member_source, run_materialization_attempt
from app.services.composite_materialization.controlled_annual_authority import (
    admit_annual_authority,
    publication_member_identities,
    require_annual_internal_bindings,
)
from app.services.composite_materialization.source_contract import _admit_published_eligibility, source_digest
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.compute_job_store import ComputeJobStore
from core.errors import APIError
from tests.composite_controlled_annual_helpers import command, graph, install_independent_test_trust, source_packet
from tests.composite_controlled_scenario_helpers import install_http_transport
from tests.composite_materialization_helpers import running_job
from tests.unit.models.test_composite_controlled_annual_contract import changing_monthly_population_receipt


@pytest.fixture
def stores(tmp_path):
    url = "sqlite:///" + (tmp_path / "annual.db").as_posix()
    ledger, facts, jobs = CompositeMaterializationStore(url), CompositeMetadataStore(url), ComputeJobStore(url)
    facts.create_schema()
    jobs.create_schema()
    try:
        yield ledger, facts, jobs, url
    finally:
        jobs._engine.dispose()
        facts.close()
        ledger.close()


def _population_variant(monkeypatch):
    """Fixed non-certifying trust for the independently signed population test variant."""
    receipt = decode_eligibility_receipt(json.dumps(changing_monthly_population_receipt()))
    install_independent_test_trust(monkeypatch)
    proof = receipt.finalization.year_authority_verification
    fields = (
        "verifier_id",
        "signer_principal_id",
        "verifier_principal_id",
        "configuration_digest",
        "signer_key_digest",
        "verifier_key_digest",
        "revocation_revision",
        "revocation_digest",
        "source_evidence_digest",
    )
    # Reuse competing_receipt's fixed public unit-test seed, never a proof-supplied trust key.
    public = Ed25519PrivateKey.from_private_bytes(bytes([17]) * 32).public_key().public_bytes_raw()
    expectation = year_ports.ControlledYearVerificationExpectation(
        request=proof.request.model_copy(deep=True),
        source_public_key_base64=base64.b64encode(public).decode(),
        source_key_valid_from="2000-01-01T00:00:00.000000Z",
        source_key_valid_to="2100-01-01T00:00:00.000000Z",
        verifier_key_valid_from="2000-01-01T00:00:00.000000Z",
        verifier_key_valid_to="2100-01-01T00:00:00.000000Z",
        **{field: getattr(proof, field) for field in fields},
    )

    class FixedPopulationVerifier:
        def verify(self, request):
            assert request == expectation.request
            return year_ports.VerifiedControlledYearEvidence(proof.model_copy(deep=True), expectation)

    monkeypatch.setattr(year_ports, "controlled_year_verifier", FixedPopulationVerifier)
    return receipt


@pytest.mark.parametrize("month,first,last", [(1, 1, 31), (1, 31, 31), (2, 1, 1), (2, 10, 20), (3, 1, 31)])
def test_population_projection_selects_the_command_month_without_granting_publication(monkeypatch, month, first, last):
    receipt = _population_variant(monkeypatch)
    definition = receipt.finalization.definition
    members = definition.authority_approval.verification.candidate_evidence[month - 1].members
    cmd = command().model_copy(update={"period_start": date(2025, month, first), "period_end": date(2025, month, last)})
    assert publication_member_identities(definition, cmd) == members


@pytest.mark.parametrize("start,end", [(date(2025, 2, 1), date(2025, 2, 28)), (date(2025, 4, 1), date(2025, 5, 31))])
def test_correct_period_population_cannot_reuse_january_publication(monkeypatch, start, end):
    receipt = _population_variant(monkeypatch)
    definition = receipt.finalization.definition
    cmd = command().model_copy(update={"period_start": start, "period_end": end})
    members = definition.authority_approval.verification.candidate_evidence[start.month - 1].members
    with pytest.raises(APIError) as error:
        admit_annual_authority(definition, cmd, [item.member_id for item in members], SimpleNamespace(receipt=receipt))
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_RESOLUTION_WINDOW_MISMATCH"


@pytest.mark.parametrize("missing", [True, False])
def test_period_projection_refuses_missing_month_or_partial_candidate_coverage(monkeypatch, missing):
    definition = _population_variant(monkeypatch).finalization.definition
    candidates = definition.authority_approval.verification.candidate_evidence
    # Defensive component proof; the wire decoder independently rejects incomplete month vectors.
    if missing:
        candidates.pop(1)
    else:
        candidates[1] = candidates[1].model_copy(update={"coverage_to": "2025-02-14"})
    cmd = command().model_copy(update={"period_start": date(2025, 2, 10), "period_end": date(2025, 2, 20)})
    with pytest.raises(APIError) as error:
        publication_member_identities(definition, cmd)
    assert error.value.error_code == (
        "COMPOSITE_YEAR_MONTH_VECTOR_MISMATCH" if missing else "COMPOSITE_UNIVERSE_COVERAGE_MISMATCH"
    )


def test_split_window_compares_full_member_identity_even_when_ids_stay_equal(monkeypatch):
    definition = _population_variant(monkeypatch).finalization.definition
    candidates = definition.authority_approval.verification.candidate_evidence
    # Isolate the defensive period comparison from the decoder's stricter annual identity-map invariant.
    members = list(candidates[2].members)
    members[0] = members[0].model_copy(update={"source_member_id": "another-source-member"})
    candidates[3] = candidates[3].model_copy(update={"members": members})
    cmd = command().model_copy(update={"period_start": date(2025, 3, 31), "period_end": date(2025, 4, 1)})
    with pytest.raises(APIError) as error:
        publication_member_identities(definition, cmd)
    assert error.value.error_code == "COMPOSITE_MEMBERSHIP_WINDOW_MISMATCH"


def test_cross_year_window_refuses_before_constructing_a_month_vector(monkeypatch):
    receipt = _population_variant(monkeypatch)
    definition = receipt.finalization.definition
    # Defensive component proof: even an invalidly expanded in-memory profile fails with the typed code.
    definition.source_authority.payload.effective_to = "2026-12-31"
    cmd = command().model_copy(update={"period_start": date(2025, 12, 31), "period_end": date(2026, 1, 1)})
    with pytest.raises(APIError) as error:
        publication_member_identities(definition, cmd)
    assert error.value.error_code == "COMPOSITE_PROFILE_WINDOW_MISMATCH"


@pytest.mark.parametrize("month,last", [(2, 28), (3, 31)])
def test_january_population_cannot_substitute_for_a_later_addition_or_removal(monkeypatch, month, last):
    receipt = _population_variant(monkeypatch)
    definition = receipt.finalization.definition
    january = definition.authority_approval.verification.candidate_evidence[0].members
    cmd = command().model_copy(update={"period_start": date(2025, month, 1), "period_end": date(2025, month, last)})
    with pytest.raises(APIError) as error:
        admit_annual_authority(definition, cmd, [item.member_id for item in january], SimpleNamespace(receipt=receipt))
    assert error.value.error_code == "COMPOSITE_AUTHORITY_UNIVERSE_MISMATCH"


def test_a_fact_window_crossing_a_population_change_requires_split_windows(monkeypatch):
    receipt = _population_variant(monkeypatch)
    definition = receipt.finalization.definition
    january = definition.authority_approval.verification.candidate_evidence[0].members
    cmd = command().model_copy(update={"period_start": date(2025, 1, 31), "period_end": date(2025, 2, 1)})
    with pytest.raises(APIError) as error:
        admit_annual_authority(definition, cmd, [item.member_id for item in january], SimpleNamespace(receipt=receipt))
    assert error.value.error_code == "COMPOSITE_MEMBERSHIP_WINDOW_MISMATCH"


def test_eligibility_request_binds_period_members_without_admitting_unavailable_publication(monkeypatch):
    receipt = _population_variant(monkeypatch)
    cmd = command().model_copy(update={"period_start": date(2025, 2, 1), "period_end": date(2025, 2, 28)})
    source = SimpleNamespace(
        definition=receipt.finalization.definition,
        wire_evidence=SimpleNamespace(attestation=source_packet()["attestation"]),
        attestation=SimpleNamespace(
            source_cut_id=cmd.source_cut_id, coverage_from=cmd.period_start, coverage_to=cmd.period_end
        ),
        published_eligibility=None,
    )
    requests = []
    native_admission = evidence_ports.admit_resolved_eligibility

    def capture(request, result):
        requests.append(request)
        return native_admission(request, result)

    monkeypatch.setattr(evidence_ports, "admit_resolved_eligibility", capture)
    with pytest.raises(APIError) as error:
        _admit_published_eligibility(source, command=cmd)
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_PUBLISHED_CUSTODY_UNAVAILABLE"
    assert requests[0].member_identities == tuple(
        receipt.finalization.year_authority_verification.candidate_evidence[1].members
    )
    assert (requests[0].effective_from, requests[0].effective_to) == ("2025-02-01", "2025-02-28")


def test_changing_annual_union_keeps_january_publication_without_inventing_financial_results(stores, monkeypatch):
    ledger, facts, jobs, _ = stores
    receipt = _population_variant(monkeypatch)
    packet = source_packet()
    packet["definition"] = receipt.finalization.definition.model_dump(mode="json")
    install_http_transport(monkeypatch, packet=packet, receipt=receipt.model_dump(mode="json"))
    cmd = command(packet)
    result = run_materialization_attempt(
        running_job(jobs, cmd, tenant_id="synthetic-tenant"), job_store=jobs, ledger=ledger, facts=facts
    )
    assert result.state == "BLOCKED" and result.expected_count == 7 and result.ready_count == 0
    assert facts.count_records(tenant_id="synthetic-tenant").member_return_facts == 0


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2025, 2, 1), date(2025, 2, 28)),
        (date(2025, 1, 31), date(2025, 2, 1)),
        (date(2025, 12, 31), date(2026, 1, 1)),
    ],
)
@pytest.mark.parametrize("retimed_unpublished_products", [False, True])
def test_unsupported_publication_window_persists_no_source_or_financial_facts(
    stores, monkeypatch, start, end, retimed_unpublished_products
):
    ledger, facts, jobs, _ = stores
    packet = source_packet()
    if retimed_unpublished_products:
        # Adversarial, rehashed products do not grant a January receipt a later or wider window.
        packet["attestation"].update(coverage_from=start.isoformat(), coverage_to=end.isoformat())
        for decision in packet["membership"]["decisions"]:
            decision.update(effective_from=start.isoformat(), effective_to=end.isoformat())
        packet["membership"]["content_hash"] = source_digest(packet["membership"])
        packet["attestation"]["membership_content_hash"] = packet["membership"]["content_hash"]
        packet["attestation"]["content_hash"] = source_digest(packet["attestation"])
    install_independent_test_trust(monkeypatch)
    install_http_transport(monkeypatch, packet=packet, receipt=graph())
    later = command(packet).model_copy(update={"period_start": start, "period_end": end})
    with pytest.raises(APIError) as error:
        run_materialization_attempt(
            running_job(jobs, later, tenant_id="synthetic-tenant"), job_store=jobs, ledger=ledger, facts=facts
        )
    expected_code = "COMPOSITE_UNIVERSE_COVERAGE_MISMATCH"
    if retimed_unpublished_products:
        expected_code = (
            "COMPOSITE_PROFILE_WINDOW_MISMATCH"
            if start.year != end.year
            else "COMPOSITE_ELIGIBILITY_RESOLUTION_WINDOW_MISMATCH"
        )
    assert error.value.error_code == expected_code
    assert facts.count_records(tenant_id="synthetic-tenant").member_return_facts == 0
    record = ledger.get(later.materialization_id, tenant_id="synthetic-tenant")
    assert record.source is None and record.outcomes == []


def test_normal_materialization_uses_native_reader_and_retains_source_without_fabricating_results(stores, monkeypatch):
    ledger, facts, jobs, url = stores
    cmd = command()
    job = running_job(jobs, cmd, tenant_id="synthetic-tenant")
    install_independent_test_trust(monkeypatch)
    calls = install_http_transport(monkeypatch, packet=source_packet(), receipt=graph())
    result = run_materialization_attempt(job, job_store=jobs, ledger=ledger, facts=facts)
    assert result.state == "BLOCKED" and result.expected_count == 7 and result.ready_count == 0
    assert result.blocked_count == 7
    assert {item.reason_code for item in result.members} == {"MEMBER_CALCULATION_REFERENCE_REQUIRED"}
    assert facts.count_records(tenant_id="synthetic-tenant").member_return_facts == 0
    assert facts.get_definition(cmd.composite_id, tenant_id="synthetic-tenant") is None
    reopened = CompositeMaterializationStore(url)
    try:
        record = reopened.get(cmd.materialization_id, tenant_id="synthetic-tenant")
        assert isinstance(record.source.definition, ControlledAnnualDefinitionV4)
        assert isinstance(_default_member_source(record.source, cmd), RetainedCompositeMemberResultSource)
        assert record.source.published_eligibility.receipt.model_dump(mode="json") == graph()
        assert record.source.wire_evidence.model_dump() == source_packet()
        monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
        assert run_materialization_attempt(job, job_store=jobs, ledger=reopened, facts=facts) == result
        assert len(calls) == 4
    finally:
        reopened.close()


@pytest.mark.parametrize("denial", ["year", "PROVIDER_TRUST", "RETURN_METHOD_CALENDAR"])
def test_missing_independent_authority_keeps_source_outcomes_and_financial_facts_absent(stores, monkeypatch, denial):
    ledger, facts, jobs, _ = stores
    cmd = command()
    job = running_job(jobs, cmd, tenant_id="synthetic-tenant")
    install_independent_test_trust(monkeypatch, denied_year=denial == "year", denied_purpose=denial)
    install_http_transport(monkeypatch, packet=source_packet(), receipt=graph())
    with pytest.raises(APIError):
        run_materialization_attempt(job, job_store=jobs, ledger=ledger, facts=facts)
    record = ledger.get(cmd.materialization_id, tenant_id="synthetic-tenant")
    assert record.state == "BLOCKED" and record.source is None and record.outcomes == []
    assert facts.count_records(tenant_id="synthetic-tenant").member_return_facts == 0


def test_source_unconfigured_preserves_waiting_and_does_not_read_or_publish(stores, monkeypatch):
    ledger, facts, jobs, _ = stores
    cmd = command()
    job = running_job(jobs, cmd, tenant_id="synthetic-tenant")
    calls = install_http_transport(monkeypatch, packet=source_packet(), receipt=graph())
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
    with pytest.raises(APIError) as error:
        run_materialization_attempt(job, job_store=jobs, ledger=ledger, facts=facts)
    assert error.value.error_code == "COMPOSITE_MEMBERSHIP_SOURCE_UNAVAILABLE"
    record = ledger.get(cmd.materialization_id, tenant_id="synthetic-tenant")
    assert record.state == "WAITING" and record.source is None and record.outcomes == []
    assert facts.count_records(tenant_id="synthetic-tenant").member_return_facts == 0 and calls == []


def test_declared_native_enrollment_never_accepts_another_product_or_contract():
    definition = decode_eligibility_receipt(json.dumps(graph())).finalization.definition
    reference = SimpleNamespace(portfolio_id=definition.source_authority.payload.member_identities[0].member_id)
    assets = SimpleNamespace(source_product="PortfolioTimeseriesInput", contract_version="portfolio-source-assets.v1")
    evidence = SimpleNamespace(contract_version="composite-member-source.v1", source_assets=assets)
    require_annual_internal_bindings(definition, command(), reference, evidence, ("MEMBER_RETURN", "BEGINNING_ASSETS"))
    for receipt in (
        SimpleNamespace(contract_version="another-contract", source_assets=assets),
        SimpleNamespace(
            contract_version=evidence.contract_version,
            source_assets=SimpleNamespace(source_product="AnotherProduct", contract_version=assets.contract_version),
        ),
    ):
        with pytest.raises(APIError) as error:
            require_annual_internal_bindings(
                definition, command(), reference, receipt, ("MEMBER_RETURN", "BEGINNING_ASSETS")
            )
        assert error.value.error_code == "COMPOSITE_YEAR_NATIVE_ENROLLMENT_MISMATCH"
    with pytest.raises(APIError) as error:
        require_annual_internal_bindings(definition, command(), reference, evidence, ("ENDING_ASSETS",))
    assert error.value.error_code == "COMPOSITE_YEAR_RULE_COVERAGE_MISMATCH"
