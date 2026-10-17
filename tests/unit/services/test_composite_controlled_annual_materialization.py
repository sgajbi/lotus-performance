"""Normal worker/owned SQLite custody; no invented native financial success."""

import json
from types import SimpleNamespace

import pytest

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource
from app.core.config import get_settings
from app.models.composite_controlled_annual_authority import ControlledAnnualDefinitionV4
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from app.services.composite_materialization.application import _default_member_source, run_materialization_attempt
from app.services.composite_materialization.controlled_annual_authority import require_annual_internal_bindings
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.compute_job_store import ComputeJobStore
from core.errors import APIError
from tests.composite_controlled_annual_helpers import command, graph, install_independent_test_trust, source_packet
from tests.composite_controlled_scenario_helpers import install_http_transport
from tests.composite_materialization_helpers import running_job


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
