"""Retained attribution replay must preserve original economics and admitted scope."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.adapters import composite_attribution_repository as repository
from app.adapters.composite_attribution_repository import AttributionInputSnapshot
from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_custody_schema import COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE
from app.ports.composite_attribution import AttributionAdmissionError
from app.services.async_result_store import AsyncResultStatus
from app.services.composite_attribution import application
from app.services.composite_attribution.admission import admit_attribution
from core.errors import APIError
from tests.composite_attribution_helpers import controlled_financial_case


@pytest.fixture
def original_case():
    request, bundle, approval, original, vector = controlled_financial_case()
    observation = admit_attribution(request, bundle, approval, tenant_id="tenant-a", original=original, vector=vector)
    response = application.build_attribution_response(request, observation, engine_version="test-native-v1")
    return request, AttributionInputSnapshot(request, observation), response


def principal():
    return VerifiedCompositePrincipal(
        "user", "checker", "tenant-a", frozenset({"operations.runtime.manage"}), frozenset({"member-a"}), "credential"
    )


@pytest.mark.parametrize(
    "members,code",
    [
        (None, "MISSING_POPULATION_COVERAGE"),
        ([], "MISSING_POPULATION_COVERAGE"),
        (["member-a", "member-a"], "MISSING_POPULATION_COVERAGE"),
        (["member-a", 1], "MISSING_POPULATION_COVERAGE"),
        (["other"], "PORTFOLIO_OUTSIDE_SCOPE"),
    ],
)
def test_attribution_scope_requires_complete_unique_authorized_population(members, code):
    with pytest.raises(APIError) as error:
        application.require_member_scope(members, principal())
    assert error.value.error_code == code
    application.require_member_scope(["member-a"], principal())


def test_durable_job_principal_cannot_cross_tenant_boundary(original_case):
    request, _, _ = original_case
    job = SimpleNamespace(
        tenant_id="tenant-b",
        request_payload=dict(
            request=request.model_dump(mode="json"),
            admitted_principal=application.principal_payload(principal()),
            admitted_portfolio_scope=["member-a"],
        ),
    )
    with pytest.raises(APIError) as error:
        application.job_principal(job)
    assert error.value.error_code == "INPUT_CUSTODY_CONFLICT"


@pytest.mark.parametrize(
    "purpose,status",
    [("TWR", AsyncResultStatus.COMPLETE), (COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE, AsyncResultStatus.FAILED)],
)
def test_retained_attribution_replay_requires_complete_purpose_bound_result(original_case, purpose, status):
    request, snapshot, response = original_case
    retained = SimpleNamespace(
        analytics_type=purpose, result_status=status, response_payload=response.model_dump(mode="json")
    )
    with pytest.raises(APIError) as error:
        application._replay_retained_result(request, snapshot, retained)
    assert error.value.error_code == "INPUT_CUSTODY_CONFLICT"


@pytest.mark.parametrize(
    "field,value",
    [
        ("calculation_id", uuid4()),
        ("composite_id", "OTHER"),
        ("input_manifest_digest", "sha256:" + "b" * 64),
        ("correction_of_calculation_id", uuid4()),
        ("official_scope_id", "sha256:" + "b" * 64),
        ("official_revision", 7),
    ],
)
def test_retained_result_cannot_substitute_original_identity(original_case, field, value):
    _, snapshot, response = original_case
    with pytest.raises(APIError) as error:
        application._require_result_original(response.model_copy(update={field: value}), snapshot)
    assert error.value.error_code == "INPUT_CUSTODY_CONFLICT"
    application._require_result_original(response, snapshot)


def test_replay_preserves_exact_financial_identity_and_effects(original_case):
    request, snapshot, response = original_case
    retained = SimpleNamespace(
        analytics_type=COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE,
        result_status=AsyncResultStatus.COMPLETE,
        response_payload=response.model_dump(mode="json"),
    )
    assert application._replay_retained_result(request, snapshot, retained) == response
    application._require_effects(request, response)
    wrong = response.model_copy(update={"financial_input_fingerprint": "sha256:" + "b" * 64})
    with pytest.raises(APIError) as error:
        application._require_financial_identity(request, wrong)
    assert error.value.error_code == "INPUT_CUSTODY_CONFLICT"
    wrong = response.model_copy(update={"outcome": response.outcome.model_copy(update={"active_return": 0.9})})
    with pytest.raises(APIError) as error:
        application._require_effects(request, wrong)
    assert error.value.error_code == "INPUT_CUSTODY_CONFLICT"


def test_result_read_of_missing_or_other_purpose_job_does_not_resolve_financial_output(monkeypatch):
    store, resolver = Mock(), Mock()
    monkeypatch.setattr(application, "compute_job_store", store)
    monkeypatch.setattr(application, "resolve_async_result", resolver)
    for job in (None, SimpleNamespace(analytics_type="TWR")):
        store.get_job_for_tenant.return_value = job
        with pytest.raises(APIError) as error:
            application.read_attribution_result(uuid4(), principal=principal())
        assert error.value.status_code == 404
    resolver.assert_not_called()


def test_publication_revalidates_financial_approval_before_any_result_write(original_case, monkeypatch):
    request, snapshot, response = original_case
    job = SimpleNamespace(
        tenant_id="tenant-a",
        request_payload=dict(
            request=request.model_dump(mode="json"),
            admitted_principal=application.principal_payload(principal()),
            admitted_portfolio_scope=["member-a"],
        ),
    )
    deployment, store, results = Mock(), Mock(), Mock()
    deployment.authority.verify.return_value = snapshot.observation.approval.model_copy(
        update={"evidence_digest": "sha256:" + "b" * 64}
    )
    monkeypatch.setattr(application, "get_composite_attribution_deployment", lambda: deployment)
    with pytest.raises(APIError) as error:
        application.publish_attribution_result(
            job, response.model_dump(mode="json"), job_store=store, result_store=results, settings=None
        )
    assert error.value.error_code == "ATTRIBUTION_PURPOSE_APPROVAL_CONFLICT"
    store.run_with_active_lease_transaction.assert_not_called()
    results.record_attribution_success_in_transaction.assert_not_called()


def queued_job(request):
    return SimpleNamespace(
        calculation_id=request.calculation_id,
        worker_id="worker",
        attempt_count=0,
        tenant_id="tenant-a",
        request_payload=dict(
            request=request.model_dump(mode="json"),
            admitted_principal=application.principal_payload(principal()),
            admitted_portfolio_scope=["member-a"],
        ),
    )


@pytest.mark.parametrize("fault", ["job-id", "request", "population", "source-refusal"])
def test_worker_refuses_inconsistent_original_before_numerical_execution(original_case, monkeypatch, fault):
    request, snapshot, _ = original_case
    job, store, deployment = queued_job(request), Mock(), Mock()
    store.run_with_active_lease_transaction.return_value = snapshot
    monkeypatch.setattr(application, "get_composite_attribution_deployment", lambda: deployment)
    if fault == "job-id":
        job.calculation_id = uuid4()
    elif fault == "request":
        store.run_with_active_lease_transaction.return_value = AttributionInputSnapshot(
            request.model_copy(update={"composite_id": "OTHER"}), snapshot.observation
        )
    else:
        store.run_with_active_lease_transaction.return_value = None
        deployment.source.read_pinned.return_value = SimpleNamespace(expected_portfolio_ids=["other"])
        if fault == "source-refusal":
            deployment.source.read_pinned.side_effect = AttributionAdmissionError(
                "SOURCE_UNAVAILABLE", "No source evidence"
            )
    with pytest.raises(APIError) as error:
        application.run_attribution_attempt(job, job_store=store, settings=None)
    assert error.value.error_code == {"population": "SOURCE_CUT_CONFLICT", "source-refusal": "SOURCE_UNAVAILABLE"}.get(
        fault, "INPUT_CUSTODY_CONFLICT"
    )
    deployment.authority.verify.assert_not_called()


def test_correction_requires_same_original_analytical_scope(original_case, monkeypatch):
    request, _, _ = original_case
    store = Mock()
    monkeypatch.setattr(application, "compute_job_store", store)
    correction = request.model_copy(update={"correction_of_calculation_id": uuid4(), "composite_id": "OTHER"})
    store.get_job_for_tenant.return_value = None
    with pytest.raises(APIError) as error:
        application._require_correction(correction, principal())
    assert error.value.status_code == 404
    store.get_job_for_tenant.return_value = SimpleNamespace(
        analytics_type=COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE,
        request_payload=dict(request=request.model_dump(mode="json"), admitted_portfolio_scope=["member-a"]),
    )
    with pytest.raises(APIError) as error:
        application._require_correction(correction, principal())
    assert error.value.error_code == "CORRECTION_SCOPE_CONFLICT"


@pytest.mark.parametrize("fault", ["digest", "identity", "projection"])
def test_repository_read_rejects_corrupt_retained_wire_and_projection(original_case, monkeypatch, fault):
    request, snapshot, _ = original_case
    payload = dict(request=request.model_dump(mode="json"), observation=snapshot.observation.model_dump(mode="json"))
    row = dict(
        payload_json=json.dumps(payload),
        payload_digest=repository.authority_digest(payload),
        calculation_id=str(request.calculation_id),
        input_manifest_digest=snapshot.observation.input_manifest_digest,
    )
    connection = Mock()
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = row
    monkeypatch.setattr(repository, "require_managed_guards", Mock())
    monkeypatch.setattr(repository, "attribution_guard_statements", lambda dialect: object())
    _, _, _, original, vector = controlled_financial_case(
        calculation_id=request.calculation_id, candidate_id=request.candidate_id
    )
    monkeypatch.setattr(repository, "retained_dependencies", lambda *args, **kwargs: (original, vector))
    if fault == "digest":
        row["payload_digest"] = "sha256:" + "b" * 64
    elif fault == "identity":
        row["calculation_id"] = str(uuid4())
    else:
        monkeypatch.setattr(
            repository,
            "admit_attribution",
            lambda *args, **kwargs: snapshot.observation.model_copy(
                update={"input_manifest_digest": "sha256:" + "b" * 64}
            ),
        )
    with pytest.raises(AttributionAdmissionError) as error:
        repository.read_attribution_input(connection, request.calculation_id, principal=principal())
    assert error.value.code == "INPUT_CUSTODY_CORRUPT"


def test_publication_requires_original_snapshot_inside_active_lease_transaction(original_case, monkeypatch):
    request, snapshot, response = original_case
    job, store, results, deployment = queued_job(request), Mock(), Mock(), Mock()
    deployment.authority.verify.return_value = snapshot.observation.approval
    monkeypatch.setattr(application, "get_composite_attribution_deployment", lambda: deployment)
    monkeypatch.setattr(application, "read_attribution_input", lambda *args, **kwargs: None)
    store.run_with_active_lease_transaction.side_effect = lambda **kwargs: kwargs["operation"](Mock())
    with pytest.raises(APIError) as error:
        application.publish_attribution_result(
            job, response.model_dump(mode="json"), job_store=store, result_store=results, settings=None
        )
    assert error.value.error_code == "INPUT_CUSTODY_CONFLICT"
    results.record_attribution_success_in_transaction.assert_not_called()
