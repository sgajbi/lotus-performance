"""Production materialization admission and durable refusal without invented economics."""

import pytest

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.core.config import get_settings
from app.models.composite_authority import ControlledScenarioDefinitionV3
from app.services.composite_materialization.application import run_materialization_attempt
from app.services.composite_metadata_store import CompositeMetadataStore
from app.services.compute_job_store import ComputeJobStore
from core.errors import APIError
from tests.composite_authority_helpers import command_for_packet
from tests.composite_controlled_scenario_helpers import (
    graph,
    install_http_transport,
    install_independent_test_trust,
    source_packet,
)
from tests.composite_materialization_helpers import running_job


@pytest.fixture
def stores(tmp_path):
    url = "sqlite:///" + (tmp_path / "scenario.db").as_posix()
    ledger, facts, jobs = CompositeMaterializationStore(url), CompositeMetadataStore(url), ComputeJobStore(url)
    facts.create_schema()
    jobs.create_schema()
    try:
        yield ledger, facts, jobs, url
    finally:
        jobs._engine.dispose()
        facts.close()
        ledger.close()


def test_normal_materialization_retains_original_graph_and_refuses_missing_provider_observations(stores, monkeypatch):
    ledger, facts, jobs, url = stores
    command = command_for_packet(source_packet())
    job = running_job(jobs, command, tenant_id="synthetic-tenant")
    install_independent_test_trust(monkeypatch)
    calls = install_http_transport(monkeypatch)
    # Neither membership nor member source is injected: both production factories execute.
    result = run_materialization_attempt(job, job_store=jobs, ledger=ledger, facts=facts)
    assert result.state == "BLOCKED" and result.blocked_count == 1 and result.ready_count == 0
    assert result.members[0].reason_code == "COMPOSITE_PROVIDER_OBSERVATION_REFUSED"
    assert [request.method for request in calls] == ["GET", "GET", "GET", "POST"]
    assert facts.count_records(tenant_id="synthetic-tenant").member_return_facts == 0
    assert facts.get_definition(command.composite_id, tenant_id="synthetic-tenant") is None

    reopened = CompositeMaterializationStore(url)
    try:
        retained = reopened.get(command.materialization_id, tenant_id="synthetic-tenant")
        assert isinstance(retained.source.definition, ControlledScenarioDefinitionV3)
        assert retained.source.wire_evidence.model_dump() == source_packet()
        assert retained.source.published_eligibility.receipt.model_dump(mode="json") == graph()
        monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
        replay = run_materialization_attempt(job, job_store=jobs, ledger=reopened, facts=facts)
        assert replay == result and len(calls) == 4
    finally:
        reopened.close()


def test_materialization_records_independent_trust_refusal_before_retaining_source(stores, monkeypatch):
    ledger, facts, jobs, _ = stores
    command = command_for_packet(source_packet())
    job = running_job(jobs, command, tenant_id="synthetic-tenant")
    install_independent_test_trust(monkeypatch, denied_purpose="ELIGIBILITY_POLICY")
    install_http_transport(monkeypatch)
    with pytest.raises(APIError, match="failed admission") as refused:
        run_materialization_attempt(job, job_store=jobs, ledger=ledger, facts=facts)
    assert refused.value.error_code == "COMPOSITE_RECEIPT_VERIFICATION_UNAVAILABLE"
    retained = ledger.get(command.materialization_id, tenant_id="synthetic-tenant")
    assert retained.state == "BLOCKED" and retained.source is None and retained.outcomes == []
    assert facts.count_records(tenant_id="synthetic-tenant").member_return_facts == 0


def test_default_unconfigured_materialization_preserves_retryable_unavailable_state(stores, monkeypatch):
    ledger, facts, jobs, _ = stores
    command = command_for_packet(source_packet())
    job = running_job(jobs, command, tenant_id="synthetic-tenant")
    calls = install_http_transport(monkeypatch)
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", None)
    with pytest.raises(APIError) as refused:
        run_materialization_attempt(job, job_store=jobs, ledger=ledger, facts=facts)
    assert refused.value.error_code == "COMPOSITE_MEMBERSHIP_SOURCE_UNAVAILABLE" and refused.value.retryable
    retained = ledger.get(command.materialization_id, tenant_id="synthetic-tenant")
    assert retained.state == "WAITING" and retained.source is None and retained.outcomes == []
    assert calls == []
