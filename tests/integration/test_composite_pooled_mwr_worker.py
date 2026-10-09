"""Controlled local custody integration; PostgreSQL and registered worker proof follow separately."""

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.adapters.composite_pooled_mwr_repository import CompositePooledMWRInputStore
from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError
from app.models.composite_authority import authority_digest
from app.models.composite_pooled_mwr import PooledSourceBundle
from app.ports.composite_pooled_mwr import PooledSourceAdmissionError
from app.services.composite_pooled_mwr.admission import admit_pooled_observation
from app.services.compute_job_store import ComputeJobLeaseOwnershipError, ComputeJobStore
from tests.unit.services.test_composite_pooled_mwr_admission import controlled_request, controlled_source_payload


@pytest.fixture
def custody_database_url(tmp_path):
    return f"sqlite:///{tmp_path / 'pooled-custody.db'}"


@pytest.fixture
def custody(custody_database_url):
    url = custody_database_url
    inputs = CompositePooledMWRInputStore(url)
    inputs.create_schema()
    jobs = ComputeJobStore(url)
    jobs.create_schema()
    request = controlled_request()
    observation = admit_pooled_observation(
        request, PooledSourceBundle.model_validate(controlled_source_payload()), tenant_id="controlled-tenant"
    )
    jobs.register_job(
        calculation_id=request.calculation_id,
        analytics_type="CompositePooledMWR",
        tenant_id="controlled-tenant",
        request_payload=request.model_dump(mode="json"),
    )
    jobs.lease_pending_jobs(worker_id="queue", limit=1, lease_seconds=60)
    jobs.mark_running_acquired(
        request.calculation_id, current_worker_id="queue", acquisition_worker_id="claim", lease_seconds=60
    )
    claim = dict(
        calculation_id=request.calculation_id,
        tenant_id="controlled-tenant",
        analytics_type="CompositePooledMWR",
        worker_id="claim",
        expected_attempt_count=1,
    )
    engine = create_engine(url)
    yield inputs, jobs, request, observation, claim, engine, url
    engine.dispose()
    inputs.close()
    jobs._engine.dispose()


def _bind(custody, *, request=None, observation=None, operation=None, claim_change=None):
    inputs, jobs, original, admitted, claim, _, _ = custody
    return jobs.run_with_active_lease_transaction(
        **{**claim, **(claim_change or {})},
        operation=operation
        or (
            lambda connection: inputs.bind(
                connection,
                tenant_id=claim["tenant_id"],
                request=request or original,
                observation=observation or admitted,
            )
        ),
    )


def test_custody_replays_original_after_reopening_store_and_is_tenant_scoped(custody):
    inputs, _, request, observation, _, engine, url = custody
    assert _bind(custody).observation == observation
    assert _bind(custody).observation == observation
    reopened = CompositePooledMWRInputStore(url)
    try:
        reopened.verify_schema()
        assert reopened.get(request.calculation_id, tenant_id="controlled-tenant").observation == observation
        assert reopened.get(request.calculation_id, tenant_id="foreign-tenant") is None
    finally:
        reopened.close()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM composite_pooled_mwr_inputs")).scalar_one() == 1
    assert inputs.get(request.calculation_id, tenant_id="controlled-tenant").request == request


def test_custody_conflicting_request_cannot_replace_original(custody):
    inputs, _, request, observation, _, _, _ = custody
    _bind(custody)
    changed = request.model_copy(update={"source_manifest_id": "controlled-correction-v2"})
    bundle = observation.source_bundle.model_copy(update={"source_manifest_id": changed.source_manifest_id})
    corrected = admit_pooled_observation(changed, bundle, tenant_id="controlled-tenant")
    with pytest.raises(PooledSourceAdmissionError) as failure:
        _bind(custody, request=changed, observation=corrected)
    assert failure.value.code == "INPUT_CUSTODY_CONFLICT"
    assert inputs.get(request.calculation_id, tenant_id="controlled-tenant").observation == observation


def test_custody_rejects_forged_projection(custody):
    inputs, _, request, observation, _, _, _ = custody
    with pytest.raises(PooledSourceAdmissionError) as failure:
        _bind(custody, observation=observation.model_copy(update={"terminal_value": Decimal("999")}))
    assert failure.value.code == "INPUT_CUSTODY_CONFLICT"
    assert inputs.get(request.calculation_id, tenant_id="controlled-tenant") is None


def test_custody_rolls_back_when_active_claim_transaction_fails(custody):
    inputs, _, request, observation, claim, _, _ = custody

    def fails_after_bind(connection):
        inputs.bind(connection, tenant_id=claim["tenant_id"], request=request, observation=observation)
        raise RuntimeError("interrupted before custody commit")

    with pytest.raises(RuntimeError, match="interrupted"):
        _bind(custody, operation=fails_after_bind)
    assert inputs.get(request.calculation_id, tenant_id="controlled-tenant") is None
    assert _bind(custody).observation == observation


@pytest.mark.parametrize("change", [{"tenant_id": "foreign"}, {"worker_id": "stale"}, {"expected_attempt_count": 2}])
def test_custody_rejects_stale_or_foreign_claim_before_insert(custody, change):
    inputs, _, request, _, _, _, _ = custody
    with pytest.raises(ComputeJobLeaseOwnershipError):
        _bind(custody, claim_change=change)
    assert inputs.get(request.calculation_id, tenant_id="controlled-tenant") is None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE composite_pooled_mwr_inputs SET payload_json='{}'",
        "DELETE FROM composite_pooled_mwr_inputs",
    ],
)
def test_database_guards_reject_mutation_and_preserve_readable_original(custody, statement):
    inputs, _, request, observation, _, engine, _ = custody
    _bind(custody)
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(text(statement))
    assert inputs.get(request.calculation_id, tenant_id="controlled-tenant").observation == observation
    inputs.verify_schema()
    inputs.create_schema()  # Explicit owner bootstrap is idempotent.


def test_catalog_drift_refuses_readiness_and_owner_bootstrap_without_repair(custody):
    inputs, _, _, _, _, engine, _ = custody
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER composite_pooled_mwr_inputs_update"))
    with pytest.raises(DurableSchemaMigrationRequiredError):
        inputs.verify_schema()
    with pytest.raises(DurableSchemaMigrationRequiredError):
        inputs.create_schema()


def test_retained_input_survives_interrupted_execution_cleanup(custody):
    inputs, _, request, observation, _, engine, _ = custody
    _bind(custody)
    # The custody table has no cascading FK to a separately pruned job/result.
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM analytics_compute_job"))
    assert inputs.get(request.calculation_id, tenant_id="controlled-tenant").observation == observation


def _corrupt_owned_fixture(engine, change):
    """Model administrative/storage corruption, then restore the required SQL guard."""
    with engine.begin() as connection:
        guard = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name='composite_pooled_mwr_inputs_update'"
        ).scalar_one()
        row = dict(connection.execute(text("SELECT * FROM composite_pooled_mwr_inputs")).mappings().one())
        change(row)
        connection.exec_driver_sql("DROP TRIGGER composite_pooled_mwr_inputs_update")
        connection.execute(
            text(
                "UPDATE composite_pooled_mwr_inputs SET payload_json=:payload_json, "
                "payload_digest=:payload_digest, input_manifest_digest=:input_manifest_digest"
            ),
            row,
        )
        connection.exec_driver_sql(guard)
    return row


@pytest.mark.parametrize("corruption", ["payload-digest", "calculation-identity", "manifest-identity"])
def test_corrupt_retained_original_refuses_read_without_repairing_storage(custody, corruption):
    inputs, _, request, _, _, engine, _ = custody
    _bind(custody)

    def corrupt(row):
        payload = json.loads(row["payload_json"])
        if corruption == "payload-digest":
            payload["observation"]["terminal_value"] = "999"
        elif corruption == "calculation-identity":
            payload["request"]["calculation_id"] = str(uuid4())
            row["payload_digest"] = authority_digest(payload)
        else:
            row["input_manifest_digest"] = "different-manifest"
        row["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    before = _corrupt_owned_fixture(engine, corrupt)
    inputs.verify_schema()
    with pytest.raises(PooledSourceAdmissionError) as error:
        inputs.get(request.calculation_id, tenant_id="controlled-tenant")
    assert error.value.code == "INPUT_CUSTODY_CORRUPT"
    with engine.connect() as connection:
        assert dict(connection.execute(text("SELECT * FROM composite_pooled_mwr_inputs")).mappings().one()) == before


@pytest.mark.parametrize("members", [[], ["member-a", "member-a"], [1], [""]])
def test_corrupt_retained_population_refuses_metadata_lookup(custody, members):
    inputs, _, request, _, _, engine, _ = custody
    _bind(custody)

    def corrupt(row):
        payload = json.loads(row["payload_json"])
        payload["observation"]["source_bundle"]["expected_portfolio_ids"] = members
        row["payload_digest"] = authority_digest(payload)
        row["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    _corrupt_owned_fixture(engine, corrupt)
    inputs.verify_schema()
    with pytest.raises(PooledSourceAdmissionError) as error:
        inputs.get_member_scope(request.calculation_id, tenant_id="controlled-tenant")
    assert error.value.code == "INPUT_CUSTODY_CORRUPT"
