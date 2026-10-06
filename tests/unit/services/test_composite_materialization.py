from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateTable

from app.adapters.composite_materialization_records import CompositeMaterializationModel
from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.adapters.composite_materialization_schema import (
    CompositeMaterializationMigrationRequiredError,
    _predicate_identity,
)
from app.adapters.composite_member_result_source import member_outcome
from app.models.composite_materialization import (
    CompositeMaterializationState,
    CompositeMemberMaterializationOutcome,
)
from app.services.composite_materialization.application import progress, run_materialization_attempt
from app.services.composite_materialization.source_contract import source_digest
from app.services.composite_metadata_store import (
    CompositeMaterializationMaintenanceRequiredError,
    CompositeMemberReturnFactSelectionError,
    CompositeMetadataStore,
)
from app.services.compute_job_store import ComputeJobLeaseOwnershipError, ComputeJobStore
from core.errors import APIError, APINotFoundError
from engine.composites import calculate_asset_weighted_composite_twr
from tests.composite_materialization_helpers import (
    INVALID_MATERIALIZATION_DATABASE_WRITES,
    MembershipSource,
    MemberSource,
    admitted,
    command_for,
    facts_for,
    running_job,
    source_products,
)


@pytest.fixture
def stores(tmp_path):
    url = "sqlite:///" + str(tmp_path / "materialization.db").replace("\\", "/")
    ledger, facts, jobs = CompositeMaterializationStore(url), CompositeMetadataStore(url), ComputeJobStore(url)
    facts.create_schema()
    jobs.create_schema()
    try:
        yield ledger, facts, jobs
    finally:
        jobs._engine.dispose()
        facts.close()
        ledger.close()


def test_manage_wire_products_admitted_without_changing_owner_hashes():
    command = command_for()
    source = admitted(command)
    assert source.attestation.content_hash == command.attestation_content_hash
    assert source.definition.performance_definition().source_authority.asset_owner == "lotus-core"
    assert source.membership.decisions[0].performance_membership("COMPOSITE").composite_id == "COMPOSITE"
    assert source.wire_evidence.attestation["attested_at"] == source_products()[2]["attested_at"]


@pytest.mark.parametrize(
    "restored",
    [
        "tenant_id = btrim(tenant_id, (chr(9) || chr(33)))",
        "tenant_id = btrim(tenant_id, (chr(9) || tenant_id))",
        "tenant_id = btrim(tenant_id, ' | ')",
    ],
)
def test_restored_tenant_predicate_only_normalizes_constant_postgres_parentheses(restored):
    expected = "tenant_id = btrim(tenant_id, chr(9) || chr(32))"
    valid = "tenant_id = btrim(tenant_id, (chr(9) || chr(32)))"
    assert _predicate_identity(expected) == _predicate_identity(valid)
    assert _predicate_identity(restored) != _predicate_identity(expected)
    assert _predicate_identity("(a AND b) OR c") != _predicate_identity("a AND (b OR c)")
    assert _predicate_identity("tenant_id = ' | '") != _predicate_identity("tenant_id = '|'")


@pytest.mark.parametrize("shape", ["partial", "weakened-check", "global-key", "global-index", "nullable-authority"])
@pytest.mark.parametrize("bootstrap", ["ledger", "shared"])
def test_restored_schema_refusal_preserves_catalog_without_adjacent_ddl(tmp_path, shape, bootstrap):
    url = "sqlite:///" + (tmp_path / "restore.db").as_posix()
    ledger, facts = CompositeMaterializationStore(url), CompositeMetadataStore(url)
    try:
        statement = str(CreateTable(CompositeMaterializationModel.__table__).compile(dialect=ledger._engine.dialect))
        if shape == "partial":
            statement = "CREATE TABLE composite_materializations (tenant_id TEXT, materialization_id TEXT)"
        elif shape == "weakened-check":
            assert "revision >= 0" in statement
            statement = statement.replace("revision >= 0", "revision >= -100")
        elif shape == "global-key":
            assert "PRIMARY KEY (tenant_id, materialization_id)" in statement
            statement = statement.replace(
                "PRIMARY KEY (tenant_id, materialization_id)", "PRIMARY KEY (materialization_id)"
            )
        elif shape == "nullable-authority":
            assert "tenant_id VARCHAR(128) NOT NULL" in statement
            statement = statement.replace("tenant_id VARCHAR(128) NOT NULL", "tenant_id VARCHAR(128)")
        with ledger._engine.begin() as connection:
            connection.exec_driver_sql(statement)
            if shape == "global-index":
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX restored_global_identity ON composite_materializations(materialization_id)"
                )
            original_sql = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name='composite_materializations'"
            ).scalar_one()
        with pytest.raises(CompositeMaterializationMigrationRequiredError):
            (ledger if bootstrap == "ledger" else facts).create_schema()
        with ledger._engine.connect() as connection:
            assert inspect(connection).get_table_names() == ["composite_materializations"]
            assert (
                connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE name='composite_materializations'"
                ).scalar_one()
                == original_sql
            )
    finally:
        ledger.close()
        facts.close()


@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "sequence",
        "actor",
        "revision",
        "command",
        "source",
        "wire",
        "typed-metadata",
        "member",
        "return",
        "release",
    ],
)
def test_retained_row_corruption_is_refused_before_disclosure_or_mutation(stores, change):
    ledger, facts, jobs = stores
    command = command_for()
    with pytest.raises(APIError):
        run_materialization_attempt(
            running_job(jobs, command),
            job_store=jobs,
            ledger=ledger,
            facts=facts,
            membership_source=MembershipSource(admitted(command)),
            member_source=MemberSource(missing="C"),
        )
    with ledger._session_factory() as session:
        row = session.get(CompositeMaterializationModel, ("tenant-a", str(command.materialization_id)))
        if change == "scope":
            row.composite_id = "OTHER"
        elif change == "sequence":
            row.restatement_sequence = 99
        elif change == "actor":
            row.actor_id = " operator "
        elif change == "revision":
            session.execute(text("PRAGMA ignore_check_constraints=ON"))
            row.revision = -1
        elif change == "command":
            row.command_json = "{}"
        elif change == "source":
            row.source_json = None
        elif change in {"wire", "typed-metadata"}:
            source = json.loads(row.source_json)
            definition = source["wire_evidence"]["definition"] if change == "wire" else source["definition"]
            definition["display_name"] = "Unexplained restored metadata"
            row.source_json = json.dumps(source)
        elif change in {"member", "return"}:
            outcomes = json.loads(row.outcomes_json)
            outcomes[0]["fact"]["portfolio_id" if change == "member" else "return_value"] = (
                "OTHER" if change == "member" else "0.99"
            )
            row.outcomes_json = json.dumps(outcomes)
        else:
            row.state = "COMPLETE"
        session.commit()
        if change == "revision":
            session.execute(text("PRAGMA ignore_check_constraints=OFF"))
    with pytest.raises(APIError) as refused:
        ledger.get(command.materialization_id, tenant_id="tenant-a")
    assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_RETAINED_EVIDENCE_REFUSED"
    assert refused.value.status_code == 503 and refused.value.retryable is False
    with pytest.raises(APINotFoundError):
        ledger.get(command.materialization_id, tenant_id="tenant-b")
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0


@pytest.mark.parametrize(
    "product,field,value,code",
    [
        (0, "tenant_id", "tenant-b", "COMPOSITE_SOURCE_SCOPE_MISMATCH"),
        (1, "definition_version", "d2", "COMPOSITE_SOURCE_SCOPE_MISMATCH"),
        (1, "source_cut_id", "cut2", "COMPOSITE_SOURCE_REVISION_MISMATCH"),
        (2, "policy_version", "policy.v2", "COMPOSITE_SOURCE_REVISION_MISMATCH"),
        (2, "posture", "INCOMPLETE", "COMPOSITE_UNIVERSE_NOT_COMPLETE"),
        (2, "posture", "UNAVAILABLE", "COMPOSITE_UNIVERSE_NOT_COMPLETE"),
        (2, "expected_portfolio_count", 2, "COMPOSITE_UNIVERSE_COUNT_MISMATCH"),
        (2, "missing_portfolio_ids", ["C"], "COMPOSITE_UNIVERSE_CONTRADICTED"),
        (2, "coverage_to", "2026-01-04", "COMPOSITE_UNIVERSE_COVERAGE_MISMATCH"),
        (2, "expected_portfolio_ids", ["A", "B", "B"], "COMPOSITE_UNIVERSE_COUNT_MISMATCH"),
    ],
)
def test_source_authority_guard_refuses_drift(product, field, value, code):
    products = list(deepcopy(source_products()))
    products[product][field] = value
    products[product]["content_hash"] = source_digest(products[product])
    command = command_for(products)
    with pytest.raises(APIError) as refusal:
        admitted(command, products)
    assert refusal.value.error_code == code


def test_source_hash_guard_refuses_rewritten_evidence():
    products = source_products()
    command = command_for(products)
    products[1]["decisions"][0]["portfolio_id"] = "REWRITTEN"
    with pytest.raises(APIError) as refusal:
        admitted(command, products)
    assert refusal.value.error_code == "COMPOSITE_SOURCE_HASH_MISMATCH"


@pytest.mark.parametrize(
    "product,path,value,code",
    [
        (0, ("source_authority", "asset_owner"), "lotus-performance", "COMPOSITE_SOURCE_OWNER_MISMATCH"),
        (0, ("reporting_currency",), "EUR", "COMPOSITE_SOURCE_POLICY_MISMATCH"),
        (0, ("inception_date",), "2026-01-06", "COMPOSITE_SOURCE_DEFINITION_WINDOW_MISMATCH"),
        (0, ("termination_date",), "2026-01-04", "COMPOSITE_SOURCE_DEFINITION_WINDOW_MISMATCH"),
        (2, ("source_products", 0, "authority_scope"), "REFERENCE_INPUT", "COMPOSITE_UNIVERSE_AUTHORITY_MISMATCH"),
        (2, ("source_products", 0, "content_hash"), "", "COMPOSITE_UNIVERSE_SOURCE_EVIDENCE_MISSING"),
        (2, ("expected_portfolio_ids",), ["A", "B", "OTHER"], "COMPOSITE_MEMBERSHIP_UNIVERSE_MISMATCH"),
        (1, ("decisions", 0, "effective_from"), "2026-01-06", "COMPOSITE_MEMBERSHIP_WINDOW_MISMATCH"),
        (1, ("decisions", 0, "effective_to"), "2026-01-04", "COMPOSITE_MEMBERSHIP_WINDOW_MISMATCH"),
    ],
)
def test_pinned_source_refuses_wrong_ownership_currency_and_effective_window(product, path, value, code):
    products = list(deepcopy(source_products()))
    target = products[product]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    products[product]["content_hash"] = source_digest(products[product])
    products[2]["membership_content_hash"] = products[1]["content_hash"]
    products[2]["content_hash"] = source_digest(products[2])
    with pytest.raises(APIError) as refused:
        admitted(command_for(products), products)
    assert refused.value.error_code == code


@pytest.mark.parametrize("shape", ["open_overlap", "closed_overlap", "partial_window", "unexpected_reference"])
def test_pinned_membership_requires_one_complete_decision_and_expected_references(shape):
    products = list(deepcopy(source_products()))
    changes = {}
    decision = products[1]["decisions"][0]
    if shape in {"open_overlap", "closed_overlap"}:
        following = {**decision, "effective_from": "2026-01-04"}
        if shape == "closed_overlap":
            decision["effective_to"] = "2026-01-04"
        products[1]["decisions"].append(following)
    elif shape == "partial_window":
        decision["effective_to"] = "2026-01-05"
        changes["period_end"] = "2026-01-06"
    else:
        references = command_for().member_calculations
        changes["member_calculations"] = [references[0].model_copy(update={"portfolio_id": "OTHER"})]
    products[1]["content_hash"] = source_digest(products[1])
    products[2]["membership_content_hash"] = products[1]["content_hash"]
    products[2]["content_hash"] = source_digest(products[2])
    with pytest.raises(APIError) as refused:
        admitted(command_for(products, **changes), products)
    assert (
        refused.value.error_code
        == {
            "open_overlap": "COMPOSITE_MEMBERSHIP_OVERLAP",
            "closed_overlap": "COMPOSITE_MEMBERSHIP_OVERLAP",
            "partial_window": "COMPOSITE_MEMBERSHIP_WINDOW_MISMATCH",
            "unexpected_reference": "COMPOSITE_MEMBER_REFERENCE_UNEXPECTED",
        }[shape]
    )
    # Adjacent inclusive windows, unlike overlapping ones, admit the exact requested day.
    valid = list(deepcopy(source_products()))
    previous = valid[1]["decisions"][0]
    following = {**previous, "effective_from": "2026-01-05"}
    previous["effective_to"] = "2026-01-04"
    valid[1]["decisions"].append(following)
    valid[1]["content_hash"] = source_digest(valid[1])
    valid[2]["membership_content_hash"] = valid[1]["content_hash"]
    valid[2]["content_hash"] = source_digest(valid[2])
    assert admitted(command_for(valid), valid).membership.decisions[-1].effective_from.isoformat() == "2026-01-05"


def test_publishing_only_authoritative_exclusions_cannot_fabricate_a_composite(stores):
    ledger, facts, _ = stores
    products = list(deepcopy(source_products()))
    for decision in products[1]["decisions"]:
        decision.update(status="EXCLUDED", reason_code="MANAGE_ELIGIBILITY_DECISION")
    products[1]["content_hash"] = source_digest(products[1])
    products[2]["membership_content_hash"] = products[1]["content_hash"]
    products[2]["content_hash"] = source_digest(products[2])
    command = command_for(products)
    original = ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    outcomes = [
        CompositeMemberMaterializationOutcome(
            portfolio_id=member, state="EXCLUDED", reason_code="MEMBER_EXCLUDED", retryable=False
        )
        for member in ("A", "B", "C")
    ]
    with pytest.raises(APIError) as refused:
        ledger.save(
            command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=0,
            source=admitted(command, products),
            outcomes=outcomes,
            state=CompositeMaterializationState.PUBLISHING,
            reason_code="COMPOSITE_PUBLICATION_PENDING",
        )
    assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_RELEASE_EMPTY"
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == original
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0


def test_progress_compare_and_swap_refuses_intervening_database_write_and_rolls_back(stores):
    """A controlled writer bypass tests CAS rollback, not real concurrent throughput."""
    ledger, facts, _ = stores
    command = command_for()
    original = ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    intervened = []

    def change_revision(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE composite_materializations SET") and not intervened:
            intervened.append(True)
            connection.execute(
                text("UPDATE composite_materializations SET revision=revision+1 WHERE materialization_id=:identity"),
                {"identity": str(command.materialization_id)},
            )

    event.listen(ledger._engine, "before_cursor_execute", change_revision)
    try:
        with pytest.raises(APIError) as refused:
            ledger.save(
                command.materialization_id,
                tenant_id="tenant-a",
                expected_revision=0,
                source=admitted(command),
                outcomes=[
                    member_outcome(member, code="PINNED_MEMBER_RESULT_PENDING", retryable=True)
                    for member in ("A", "B", "C")
                ],
                state=CompositeMaterializationState.WAITING,
                reason_code="COMPOSITE_MEMBERS_PENDING",
            )
        assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_REVISION_CONFLICT"
    finally:
        event.remove(ledger._engine, "before_cursor_execute", change_revision)
    assert intervened == [True]
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == original
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0


def test_progress_refuses_ready_fact_without_admitted_calculation_reference(stores):
    ledger, facts, _ = stores
    original = command_for()
    members = MemberSource()
    outcomes = [
        members.read_member(
            original,
            reference,
            tenant_id="tenant-a",
            membership_snapshot_id=original.membership_content_hash,
            request_headers={"x-tenant-id": "tenant-a"},
        )
        for reference in original.member_calculations
    ]
    command = original.model_copy(update={"member_calculations": original.member_calculations[1:]})
    reserved = ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    with pytest.raises(APIError) as refused:
        ledger.save(
            command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=0,
            source=admitted(command),
            outcomes=outcomes,
            state=CompositeMaterializationState.PUBLISHING,
            reason_code="COMPOSITE_PUBLICATION_PENDING",
        )
    assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_FACT_SCOPE_MISMATCH"
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == reserved
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0


@pytest.mark.parametrize("status", ["EXCLUDED", "PENDING_REVIEW", "NON_DISCRETIONARY", "MISSING_REFERENCE"])
def test_worker_retains_explicit_eligibility_or_missing_reference_without_inventing_economics(stores, status):
    ledger, facts, jobs = stores
    products = list(deepcopy(source_products()))
    decisions = products[1]["decisions"]
    if status in {"EXCLUDED", "PENDING_REVIEW"}:
        for item in decisions:
            item.update(status=status, reason_code="MANAGE_ELIGIBILITY_DECISION")
    elif status == "NON_DISCRETIONARY":
        decisions[0]["discretionary"] = False
    products[1]["content_hash"] = source_digest(products[1])
    products[2]["membership_content_hash"] = products[1]["content_hash"]
    products[2]["content_hash"] = source_digest(products[2])
    command = command_for(products, **({"member_calculations": []} if status == "MISSING_REFERENCE" else {}))
    members = MemberSource()
    result = run_materialization_attempt(
        running_job(jobs, command),
        job_store=jobs,
        ledger=ledger,
        facts=facts,
        membership_source=MembershipSource(admitted(command, products)),
        member_source=members,
    )
    assert result.state == "BLOCKED" and result.retryable is False
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0
    expected_states = {
        "EXCLUDED": ["EXCLUDED"] * 3,
        "PENDING_REVIEW": ["BLOCKED"] * 3,
        "NON_DISCRETIONARY": ["BLOCKED", "READY", "READY"],
        "MISSING_REFERENCE": ["BLOCKED"] * 3,
    }
    assert [item.state for item in result.members] == expected_states[status]
    assert members.reads == (["B", "C"] if status == "NON_DISCRETIONARY" else [])


@pytest.mark.parametrize("retryable", [True, False])
def test_source_failure_retains_truthful_waiting_or_terminal_refusal(stores, retryable):
    ledger, facts, jobs = stores
    command = command_for()

    class UnavailableSource:
        async def read_pinned(self, *args, **kwargs):
            raise APIError(503 if retryable else 422, "source-safe refusal", retryable=retryable)

    with pytest.raises(APIError):
        run_materialization_attempt(
            running_job(jobs, command),
            job_store=jobs,
            ledger=ledger,
            facts=facts,
            membership_source=UnavailableSource(),
            member_source=MemberSource(),
        )
    retained = ledger.get(command.materialization_id, tenant_id="tenant-a")
    assert retained.source is None and retained.outcomes == []
    assert retained.state == ("WAITING" if retryable else "BLOCKED")
    assert retained.reason_code == ("COMPOSITE_SOURCE_UNAVAILABLE" if retryable else "COMPOSITE_SOURCE_REFUSED")
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0


@pytest.mark.parametrize("status", ["INCLUDED", "EXCLUDED", "PENDING_REVIEW"])
def test_durable_progress_cannot_override_manage_eligibility(stores, status):
    ledger, _, _ = stores
    products = list(deepcopy(source_products()))
    products[1]["decisions"][0].update(status=status, reason_code="MANAGE_DECISION")
    products[1]["content_hash"] = source_digest(products[1])
    products[2]["membership_content_hash"] = products[1]["content_hash"]
    products[2]["content_hash"] = source_digest(products[2])
    command = command_for(products)
    prior = ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    outcomes = [member_outcome(member, code="PENDING", retryable=True) for member in ("A", "B", "C")]
    if status == "INCLUDED":
        outcomes[0] = CompositeMemberMaterializationOutcome(
            portfolio_id="A", state="EXCLUDED", reason_code="CALLER_EXCLUSION", retryable=False
        )
    with pytest.raises(APIError) as refused:
        ledger.save(
            command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=0,
            source=admitted(command, products),
            outcomes=outcomes,
            state=CompositeMaterializationState.WAITING,
            reason_code="PENDING",
        )
    assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_ELIGIBILITY_MISMATCH"
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == prior


@pytest.mark.parametrize("field,value", INVALID_MATERIALIZATION_DATABASE_WRITES)
def test_sqlite_materialization_database_refuses_malformed_scope_and_progress(stores, field, value):
    ledger, _, _ = stores
    command = command_for()
    original = ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    with pytest.raises(DBAPIError), ledger._engine.begin() as connection:
        connection.execute(
            text(f"UPDATE composite_materializations SET {field}=:value WHERE materialization_id=:identity"),
            {"value": value, "identity": str(command.materialization_id)},
        )
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == original


def test_materialization_missing_member_recovers_after_store_restart_without_survivorship(stores):
    ledger, facts, jobs = stores
    command = command_for()
    membership, members = MembershipSource(admitted(command)), MemberSource(missing="C")
    job = running_job(jobs, command)
    with pytest.raises(APIError) as pending:
        run_materialization_attempt(
            job, job_store=jobs, ledger=ledger, facts=facts, membership_source=membership, member_source=members
        )
    assert pending.value.retryable
    partial = ledger.get(command.materialization_id, tenant_id="tenant-a")
    assert (progress(partial).ready_count, progress(partial).waiting_count) == (2, 1)
    assert partial.outcomes[-1].fact is None
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0
    members.missing = None
    restarted_ledger = CompositeMaterializationStore(str(ledger._engine.url))
    try:
        complete = run_materialization_attempt(
            job,
            job_store=jobs,
            ledger=restarted_ledger,
            facts=facts,
            membership_source=membership,
            member_source=members,
        )
    finally:
        restarted_ledger.close()
    assert complete.state == "COMPLETE"
    assert membership.reads == 1
    assert members.reads == ["A", "B", "C", "C"]
    rows = facts_for(facts)
    result = calculate_asset_weighted_composite_twr(composite_id="COMPOSITE", member_return_facts=rows)
    assert result.period_results[0].return_value == (Decimal(14) / Decimal(600)).quantize(Decimal("0.000000000001"))
    assert sum(row.beginning_market_value for row in rows) == Decimal(600)
    assert sum(row.ending_market_value for row in rows) == Decimal(614)
    replay = run_materialization_attempt(
        job, job_store=jobs, ledger=ledger, facts=facts, membership_source=membership, member_source=members
    )
    assert replay == complete
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 3


def test_older_admitted_generation_can_finish_without_replacing_newer_correction(stores):
    ledger, facts, jobs = stores
    original = command_for()
    original_job = running_job(jobs, original)
    with pytest.raises(APIError):
        run_materialization_attempt(
            original_job,
            job_store=jobs,
            ledger=ledger,
            facts=facts,
            membership_source=MembershipSource(admitted(original)),
            member_source=MemberSource(missing="C"),
        )
    corrected = command_for(corrected=True, restatement_sequence=2)
    result = run_materialization_attempt(
        running_job(jobs, corrected),
        job_store=jobs,
        ledger=ledger,
        facts=facts,
        membership_source=MembershipSource(admitted(corrected)),
        member_source=MemberSource(corrected=True),
    )
    assert result.state == "COMPLETE"
    latest_before = facts_for(facts)
    assert {item.restatement_sequence for item in latest_before} == {2}
    resumed = run_materialization_attempt(
        original_job,
        job_store=jobs,
        ledger=ledger,
        facts=facts,
        membership_source=MembershipSource(admitted(original)),
        member_source=MemberSource(),
    )
    assert resumed.state == "COMPLETE"
    assert facts_for(facts) == latest_before
    historical = facts_for(facts, sequence=1)
    assert {item.restatement_sequence for item in historical} == {1}
    assert sum(item.beginning_market_value * item.return_value for item in historical) == Decimal(14)
    assert sum(item.beginning_market_value * item.return_value for item in latest_before) == Decimal(24)


@pytest.mark.parametrize("restart", [False, True])
def test_bounded_member_attempts_do_not_starve_later_available_members(stores, monkeypatch, restart):
    ledger, facts, jobs = stores
    command = command_for()
    job = running_job(jobs, command)
    membership, members = MembershipSource(admitted(command)), MemberSource(missing="A")
    monkeypatch.setattr("app.services.composite_materialization.application._MAX_MEMBERS_PER_ATTEMPT", 1)
    try:
        for _ in range(3):
            with pytest.raises(APIError) as pending:
                run_materialization_attempt(
                    job,
                    job_store=jobs,
                    ledger=ledger,
                    facts=facts,
                    membership_source=membership,
                    member_source=members,
                )
            assert pending.value.error_code == "COMPOSITE_MEMBERS_PENDING"
            if restart:
                url = ledger._engine.url.render_as_string(hide_password=False)
                ledger.close()
                ledger = CompositeMaterializationStore(url)
        retained = ledger.get(command.materialization_id, tenant_id="tenant-a")
        assert members.reads == ["A", "B", "C"]
        assert [outcome.state for outcome in retained.outcomes] == ["WAITING", "READY", "READY"]
        assert [outcome.inspection_attempts for outcome in retained.outcomes] == [1, 1, 1]
        assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0
        assert membership.reads == 1
        members.missing = None
        complete = run_materialization_attempt(
            job,
            job_store=jobs,
            ledger=ledger,
            facts=facts,
            membership_source=membership,
            member_source=members,
        )
        assert complete.state == "COMPLETE"
        assert members.reads == ["A", "B", "C", "A"]
        assert [outcome.inspection_attempts for outcome in complete.members] == [2, 1, 1]
        assert sum(item.beginning_market_value * item.return_value for item in facts_for(facts)) == Decimal(14)
    finally:
        if restart:
            ledger.close()


@pytest.mark.parametrize("invalid_count", [0, 3])
def test_member_inspection_count_cannot_rewind_or_skip_progress(stores, invalid_count):
    ledger, _, jobs = stores
    command = command_for()
    with pytest.raises(APIError, match="pending"):
        run_materialization_attempt(
            running_job(jobs, command),
            job_store=jobs,
            ledger=ledger,
            facts=stores[1],
            membership_source=MembershipSource(admitted(command)),
            member_source=MemberSource(missing="A"),
        )
    retained = ledger.get(command.materialization_id, tenant_id="tenant-a")
    outcomes = list(retained.outcomes)
    outcomes[0] = outcomes[0].model_copy(update={"inspection_attempts": invalid_count})
    with pytest.raises(APIError) as refusal:
        ledger.save(
            command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=retained.revision,
            source=retained.source,
            outcomes=outcomes,
            state=retained.state,
            reason_code=retained.reason_code,
        )
    assert refusal.value.error_code == "COMPOSITE_MATERIALIZATION_INSPECTION_COUNT_REFUSED"
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == retained


def test_ledger_scope_replay_conflict_and_cross_tenant_identifier(stores):
    ledger, _, _ = stores
    command = command_for()
    first = ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    replay = ledger.register(
        command.model_copy(update={"calculation_id": uuid4()}), tenant_id="tenant-a", actor_id="operator"
    )
    assert replay == first
    other = ledger.register(command, tenant_id="tenant-b", actor_id="other-operator")
    assert other.actor_id == "other-operator"
    assert ledger.get(command.materialization_id, tenant_id="tenant-a").actor_id == "operator"
    assert ledger.get_many([command.materialization_id], tenant_id="tenant-a") == [first]
    assert ledger.get_many([command.materialization_id], tenant_id="tenant-b") == [other]
    for invalid in ([], [command.materialization_id] * 2, [uuid4() for _ in range(121)]):
        with pytest.raises(ValueError, match="1..120 unique"):
            ledger.get_many(invalid, tenant_id="tenant-a")
    with pytest.raises(APINotFoundError):
        ledger.get_many([command.materialization_id], tenant_id="tenant-c")
    with pytest.raises(APIError) as changed:
        ledger.register(
            command.model_copy(update={"source_cut_id": "different"}), tenant_id="tenant-a", actor_id="operator"
        )
    assert changed.value.error_code == "COMPOSITE_MATERIALIZATION_CONTENT_CONFLICT"
    with pytest.raises(APIError) as conflict:
        ledger.register(
            command.model_copy(update={"materialization_id": uuid4()}), tenant_id="tenant-a", actor_id="operator"
        )
    assert conflict.value.error_code == "COMPOSITE_MATERIALIZATION_SCOPE_CONFLICT"


def test_stale_worker_has_no_member_or_publication_effects(stores):
    ledger, facts, jobs = stores
    command = command_for()
    job = running_job(jobs, command)
    membership = MembershipSource(admitted(command))
    with pytest.raises(ComputeJobLeaseOwnershipError):
        run_materialization_attempt(
            replace(job, worker_id="stale-worker"),
            job_store=jobs,
            ledger=ledger,
            facts=facts,
            membership_source=membership,
            member_source=MemberSource(),
        )
    assert membership.reads == 0
    assert facts.count_records(tenant_id="tenant-a").member_return_facts == 0
    with pytest.raises(APINotFoundError):
        ledger.get(command.materialization_id, tenant_id="tenant-a")


def test_pending_correction_refuses_latest_but_preserves_explicit_original(stores):
    ledger, facts, jobs = stores
    original = command_for()
    run_materialization_attempt(
        running_job(jobs, original),
        job_store=jobs,
        ledger=ledger,
        facts=facts,
        membership_source=MembershipSource(admitted(original)),
        member_source=MemberSource(),
    )
    original_rows = facts_for(facts, sequence=1)
    jobs.mark_complete(original.calculation_id, response_payload={}, worker_id="worker-a")
    corrected = command_for(corrected=True, restatement_sequence=2)
    job = running_job(jobs, corrected)
    members = MemberSource(missing="C", corrected=True)
    with pytest.raises(APIError):
        run_materialization_attempt(
            job,
            job_store=jobs,
            ledger=ledger,
            facts=facts,
            membership_source=MembershipSource(admitted(corrected)),
            member_source=members,
        )
    with pytest.raises(CompositeMemberReturnFactSelectionError):
        facts_for(facts)
    assert facts_for(facts, sequence=1) == original_rows
    members.missing = None
    run_materialization_attempt(
        job,
        job_store=jobs,
        ledger=ledger,
        facts=facts,
        membership_source=MembershipSource(admitted(corrected)),
        member_source=members,
    )
    result = calculate_asset_weighted_composite_twr(composite_id="COMPOSITE", member_return_facts=facts_for(facts))
    assert result.period_results[0].return_value == Decimal("0.04")
    assert facts_for(facts, sequence=1) == original_rows


def test_progress_pages_include_missing_member_and_exhaustion(stores):
    ledger, facts, jobs = stores
    command = command_for()
    with pytest.raises(APIError):
        run_materialization_attempt(
            running_job(jobs, command),
            job_store=jobs,
            ledger=ledger,
            facts=facts,
            membership_source=MembershipSource(admitted(command)),
            member_source=MemberSource(missing="C"),
        )
    record = ledger.get(command.materialization_id, tenant_id="tenant-a")
    first, final = progress(record, limit=2), progress(record, offset=2, limit=2)
    assert (first.expected_count, first.ready_count, first.waiting_count, first.next_offset) == (3, 2, 1, 2)
    assert final.members[0].portfolio_id == "C"
    assert final.members[0].state == "WAITING"
    assert final.next_offset is None


@pytest.mark.parametrize("selective", [False, True])
def test_fact_only_cleanup_cannot_orphan_governed_materialization_evidence(stores, selective):
    ledger, facts, jobs = stores
    command = command_for()
    run_materialization_attempt(
        running_job(jobs, command),
        job_store=jobs,
        ledger=ledger,
        facts=facts,
        membership_source=MembershipSource(admitted(command)),
        member_source=MemberSource(),
    )
    original_facts = facts_for(facts)
    original_progress = ledger.get(command.materialization_id, tenant_id="tenant-a")
    with pytest.raises(CompositeMaterializationMaintenanceRequiredError):
        if selective:
            facts.clear_records_for_composites({command.composite_id}, tenant_id="tenant-a")
        else:
            facts.clear_all_records(tenant_id="tenant-a")
    assert facts_for(facts) == original_facts
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == original_progress
    # The refusal is scoped, not an estate-wide cleanup ban.
    facts.clear_all_records(tenant_id="tenant-b")
    facts.clear_records_for_composites({"UNRELATED_COMPOSITE"}, tenant_id="tenant-a")
    assert facts_for(facts) == original_facts


def test_optimistic_progress_rejects_stale_revision(stores):
    ledger, _, _ = stores
    command = command_for()
    ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    ledger.save(
        command.materialization_id,
        tenant_id="tenant-a",
        expected_revision=0,
        source=admitted(command),
        outcomes=[
            member_outcome(member, code="PINNED_MEMBER_RESULT_PENDING", retryable=True) for member in ("A", "B", "C")
        ],
        state=CompositeMaterializationState.WAITING,
        reason_code="COMPOSITE_MEMBERS_PENDING",
    )
    with pytest.raises(APIError) as stale:
        ledger.save(
            command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=0,
            source=admitted(command),
            outcomes=[
                member_outcome(member, code="PINNED_MEMBER_RESULT_PENDING", retryable=True)
                for member in ("A", "B", "C")
            ],
            state=CompositeMaterializationState.WAITING,
            reason_code="COMPOSITE_MEMBERS_PENDING",
        )
    assert stale.value.error_code == "COMPOSITE_MATERIALIZATION_REVISION_CONFLICT"


@pytest.mark.parametrize(
    "change,expected_code",
    [
        ("source_removed", "COMPOSITE_MATERIALIZATION_SOURCE_IMMUTABLE"),
        ("source_rewritten", "COMPOSITE_MATERIALIZATION_SOURCE_IMMUTABLE"),
        ("member_omitted", "COMPOSITE_MATERIALIZATION_UNIVERSE_INCOMPLETE"),
        ("member_duplicated", "COMPOSITE_MATERIALIZATION_UNIVERSE_INCOMPLETE"),
        ("member_foreign", "COMPOSITE_MATERIALIZATION_UNIVERSE_INCOMPLETE"),
        ("publishing_missing", "COMPOSITE_MATERIALIZATION_RELEASE_INCOMPLETE"),
        ("complete_shortcut", "COMPOSITE_MATERIALIZATION_TRANSITION_REFUSED"),
    ],
)
def test_progress_rejects_source_loss_survivorship_and_release_shortcuts(stores, change, expected_code):
    ledger, _, _ = stores
    command = command_for()
    source = admitted(command)
    waiting = [
        member_outcome(member, code="PINNED_MEMBER_RESULT_PENDING", retryable=True) for member in ("A", "B", "C")
    ]
    ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    prior = ledger.save(
        command.materialization_id,
        tenant_id="tenant-a",
        expected_revision=0,
        source=source,
        outcomes=waiting,
        state=CompositeMaterializationState.WAITING,
        reason_code="COMPOSITE_MEMBERS_PENDING",
    )
    outcomes = list(waiting)
    state = CompositeMaterializationState.WAITING
    if change == "source_removed":
        source = None
    elif change == "source_rewritten":
        source = source.model_copy(
            update={"definition": source.definition.model_copy(update={"display_name": "Rewritten"})}
        )
    elif change == "member_omitted":
        outcomes.pop()
    elif change == "member_duplicated":
        outcomes[2] = outcomes[1]
    elif change == "member_foreign":
        outcomes[2] = member_outcome("OTHER", code="PINNED_MEMBER_RESULT_PENDING", retryable=True)
    elif change == "publishing_missing":
        state = CompositeMaterializationState.PUBLISHING
    elif change == "complete_shortcut":
        state = CompositeMaterializationState.COMPLETE
    with pytest.raises(APIError) as refusal:
        ledger.save(
            command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=prior.revision,
            source=source,
            outcomes=outcomes,
            state=state,
            reason_code="COMPOSITE_MEMBERS_PENDING",
        )
    assert refusal.value.error_code == expected_code
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == prior


def test_progress_retains_ready_economics_and_refuses_fact_scope_changes(stores):
    ledger, _, _ = stores
    command = command_for()
    source = admitted(command)
    members = MemberSource()
    outcomes = [
        members.read_member(
            command,
            reference,
            tenant_id="tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={"x-tenant-id": "tenant-a"},
        )
        for reference in command.member_calculations
    ]
    ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    invalid = [
        outcomes[0].model_copy(update={"fact": outcomes[0].fact.model_copy(update={"reporting_currency": "EUR"})}),
        *outcomes[1:],
    ]
    with pytest.raises(APIError) as mismatch:
        ledger.save(
            command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=0,
            source=source,
            outcomes=invalid,
            state=CompositeMaterializationState.WAITING,
            reason_code="COMPOSITE_MEMBERS_PENDING",
        )
    assert mismatch.value.error_code == "COMPOSITE_MATERIALIZATION_FACT_SCOPE_MISMATCH"
    prior = ledger.save(
        command.materialization_id,
        tenant_id="tenant-a",
        expected_revision=0,
        source=source,
        outcomes=outcomes,
        state=CompositeMaterializationState.WAITING,
        reason_code="COMPOSITE_MEMBERS_PENDING",
    )
    rewritten = [
        outcomes[0].model_copy(update={"fact": outcomes[0].fact.model_copy(update={"return_value": Decimal("0.5")})}),
        *outcomes[1:],
    ]
    with pytest.raises(APIError) as immutable:
        ledger.save(
            command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=prior.revision,
            source=source,
            outcomes=rewritten,
            state=CompositeMaterializationState.WAITING,
            reason_code="COMPOSITE_MEMBERS_PENDING",
        )
    assert immutable.value.error_code == "COMPOSITE_MATERIALIZATION_OUTCOME_IMMUTABLE"
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == prior


def test_acquired_attempt_owner_not_historical_worker_controls_materialization(stores):
    ledger, facts, jobs = stores
    command = command_for()
    previous = running_job(jobs, command)
    jobs.mark_running_acquired(
        command.calculation_id, current_worker_id="worker-a", acquisition_worker_id="attempt-owner", lease_seconds=60
    )
    current = jobs.get_job_for_tenant(command.calculation_id, tenant_id="tenant-a")
    assert current.worker_id == "worker-a" and current.attempt_count == previous.attempt_count + 1
    membership = MembershipSource(admitted(command))
    for stale in (
        previous,
        replace(current, worker_id=None),
        replace(current, worker_id="worker-a"),
        replace(previous, worker_id="attempt-owner"),
    ):
        with pytest.raises(ComputeJobLeaseOwnershipError):
            run_materialization_attempt(
                stale,
                job_store=jobs,
                ledger=ledger,
                facts=facts,
                membership_source=membership,
                member_source=MemberSource(),
            )
    assert membership.reads == 0
    with pytest.raises(APINotFoundError):
        ledger.get(command.materialization_id, tenant_id="tenant-a")
    complete = run_materialization_attempt(
        replace(current, worker_id="attempt-owner"),
        job_store=jobs,
        ledger=ledger,
        facts=facts,
        membership_source=membership,
        member_source=MemberSource(),
    )
    assert complete.state == CompositeMaterializationState.COMPLETE


def test_reserved_chronology_cannot_be_reopened_by_a_late_command(stores):
    ledger, _, _ = stores
    newest = command_for(restatement_sequence=2)
    ledger.register(newest, tenant_id="tenant-a", actor_id="operator")
    stale = command_for(restatement_sequence=1)
    with pytest.raises(APIError) as refusal:
        ledger.register(stale, tenant_id="tenant-a", actor_id="operator")
    assert refusal.value.error_code == "COMPOSITE_MATERIALIZATION_SCOPE_CONFLICT"
    with pytest.raises(APINotFoundError):
        ledger.get(stale.materialization_id, tenant_id="tenant-a")
    other = ledger.register(stale, tenant_id="tenant-b", actor_id="other-operator")
    assert other.command.restatement_sequence == 1


def test_complete_requires_exact_existing_fact_publication(stores):
    ledger, _, _ = stores
    command = command_for()
    source = admitted(command)
    members = MemberSource()
    outcomes = [
        members.read_member(
            command,
            reference,
            tenant_id="tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={"x-tenant-id": "tenant-a"},
        )
        for reference in command.member_calculations
    ]
    ledger.register(command, tenant_id="tenant-a", actor_id="operator")
    publishing = ledger.save(
        command.materialization_id,
        tenant_id="tenant-a",
        expected_revision=0,
        source=source,
        outcomes=outcomes,
        state=CompositeMaterializationState.PUBLISHING,
        reason_code="COMPOSITE_PUBLICATION_PENDING",
    )
    with pytest.raises(APIError) as missing:
        ledger.save(
            command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=publishing.revision,
            source=source,
            outcomes=outcomes,
            state=CompositeMaterializationState.COMPLETE,
            reason_code=None,
        )
    assert missing.value.error_code == "COMPOSITE_MATERIALIZATION_PUBLICATION_REQUIRED"
    assert ledger.get(command.materialization_id, tenant_id="tenant-a") == publishing
