"""Refuse inconsistent retained/queued authority before new financial side effects."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_custody_schema import COMPOSITE_POOLED_ANALYTICS_TYPE
from app.api.dependencies.composite_pooled_mwr import require_pooled_principal
from app.models.composite_pooled_mwr import CompositePooledMWRResponse, PooledSourceBundle
from app.ports.composite_pooled_mwr import PooledSourceAdmissionError
from app.services.async_result_store import AsyncResultStatus
from app.services.composite_pooled_mwr import application
from app.services.composite_pooled_mwr.admission import admit_pooled_observation
from app.services.composite_pooled_mwr.solver_adapter import calculate_pooled_xirr
from core.errors import APIError
from tests.unit.services.test_composite_pooled_mwr_admission import controlled_request, controlled_source_payload


@pytest.fixture
def pooled_context(monkeypatch):
    request = controlled_request()
    bundle = PooledSourceBundle.model_validate(controlled_source_payload())
    observation = admit_pooled_observation(request, bundle, tenant_id="controlled-tenant")
    snapshot = SimpleNamespace(request=request, observation=observation)
    principal = VerifiedCompositePrincipal(
        principal_kind="USER",
        subject="controlled-subject",
        tenant_id="controlled-tenant",
        capabilities=frozenset(),
        portfolio_scope=frozenset(bundle.expected_portfolio_ids),
        credential_id="controlled-credential",
    )
    inputs = Mock()
    inputs.get_member_scope.return_value = tuple(bundle.expected_portfolio_ids)
    inputs.get.return_value = snapshot
    inputs.read_in_transaction.return_value = snapshot
    reader = Mock()
    reader.read_population_scope.return_value = tuple(bundle.expected_portfolio_ids)
    reader.read_pinned.return_value = bundle
    result_store = Mock()
    result_store.get_result_for_tenant.return_value = None
    job_store = Mock()
    job_store.run_with_active_lease_transaction.side_effect = lambda **kwargs: kwargs["operation"](object())
    job = SimpleNamespace(
        calculation_id=request.calculation_id,
        tenant_id="controlled-tenant",
        worker_id="controlled-worker",
        attempt_count=0,
        request_payload={
            "request": request.model_dump(mode="json"),
            "admitted_portfolio_scope": list(bundle.expected_portfolio_ids),
        },
    )
    settings = SimpleNamespace(LINEAGE_METADATA_DATABASE_URL="controlled-unused-database")
    register = Mock()
    monkeypatch.setattr(application, "get_composite_pooled_mwr_input_store", lambda **kwargs: inputs)
    monkeypatch.setattr(application, "get_pooled_monetary_source_reader", lambda: reader)
    monkeypatch.setattr(application, "get_async_result_store", lambda **kwargs: result_store)
    monkeypatch.setattr(application, "register_async_submission_or_raise", register)
    return SimpleNamespace(
        request=request,
        observation=observation,
        principal=principal,
        inputs=inputs,
        reader=reader,
        result_store=result_store,
        job_store=job_store,
        job=job,
        settings=settings,
        register=register,
    )


@pytest.mark.parametrize("retained", [None, "different-request"])
def test_retained_population_without_matching_original_refuses_submission(pooled_context, retained):
    context = pooled_context
    context.inputs.get.return_value = (
        None
        if retained is None
        else SimpleNamespace(request=context.request.model_copy(update={"source_manifest_id": "different-cut"}))
    )
    with pytest.raises(APIError) as error:
        application.submit_pooled_mwr(context.request, principal=context.principal)
    assert error.value.error_code == "INPUT_CUSTODY_CONFLICT"
    context.register.assert_not_called()
    context.reader.read_pinned.assert_not_called()


def test_population_source_failure_preserves_typed_unavailability_without_submission(pooled_context):
    context = pooled_context
    context.inputs.get_member_scope.return_value = None
    context.reader.read_population_scope.side_effect = PooledSourceAdmissionError("SOURCE_CUT_UNAVAILABLE", "absent")
    with pytest.raises(APIError) as error:
        application.submit_pooled_mwr(context.request, principal=context.principal)
    assert error.value.error_code == "SOURCE_CUT_UNAVAILABLE"
    context.register.assert_not_called()
    context.inputs.get.assert_not_called()


@pytest.mark.parametrize("missing", ["population", "original", "analytical-scope"])
def test_correction_refuses_missing_or_different_original_before_registration(pooled_context, missing):
    context = pooled_context
    correction = context.request.model_copy(
        update={"calculation_id": uuid4(), "correction_of_calculation_id": context.request.calculation_id}
    )
    context.inputs.get_member_scope.side_effect = [None, None if missing == "population" else ("member-a", "member-b")]
    if missing == "original":
        context.inputs.get.return_value = None
    if missing == "analytical-scope":
        correction = correction.model_copy(update={"composite_id": "different-composite"})
    with pytest.raises(APIError) as error:
        application.submit_pooled_mwr(correction, principal=context.principal)
    assert error.value.status_code == (404 if missing == "population" else 409)
    if missing != "population":
        assert error.value.error_code == (
            "CORRECTION_SCOPE_CONFLICT" if missing == "analytical-scope" else "INPUT_CUSTODY_CONFLICT"
        )
    context.register.assert_not_called()
    context.reader.read_pinned.assert_not_called()


@pytest.mark.parametrize("conflict", ["calculation", "population", "source-unavailable", "retained-request"])
def test_worker_refuses_inconsistent_job_or_source_before_new_input_bind(pooled_context, conflict):
    context = pooled_context
    if conflict == "calculation":
        context.job.calculation_id = uuid4()
    elif conflict in {"population", "source-unavailable"}:
        context.inputs.read_in_transaction.return_value = None
        if conflict == "population":
            context.job.request_payload["admitted_portfolio_scope"] = ["member-a"]
        else:
            context.reader.read_pinned.side_effect = PooledSourceAdmissionError("SOURCE_CUT_UNAVAILABLE", "absent")
    else:
        context.inputs.read_in_transaction.return_value = SimpleNamespace(
            request=context.request.model_copy(update={"source_manifest_id": "different-cut"})
        )
    with pytest.raises(APIError) as error:
        application.run_pooled_mwr_attempt(context.job, job_store=context.job_store, settings=context.settings)
    expected = {"population": "SOURCE_CUT_CONFLICT", "source-unavailable": "SOURCE_CUT_UNAVAILABLE"}
    assert error.value.error_code == expected.get(conflict, "INPUT_CUSTODY_CONFLICT")
    context.inputs.bind.assert_not_called()
    context.result_store.record_pooled_success_in_transaction.assert_not_called()


def _response(context):
    return CompositePooledMWRResponse(
        calculation_id=context.request.calculation_id,
        composite_id=context.request.composite_id,
        input_manifest_digest=context.observation.input_manifest_digest,
        calculation_engine_version="controlled-engine",
        correction_of_calculation_id=None,
        observation=context.observation,
        outcome=calculate_pooled_xirr(context.request, context.observation),
    )


@pytest.mark.parametrize("conflict", ["purpose", "status", "observation"])
def test_worker_cannot_replay_foreign_purpose_or_different_retained_inputs(pooled_context, conflict):
    context = pooled_context
    response = _response(context)
    if conflict == "observation":
        response = response.model_copy(
            update={"observation": context.observation.model_copy(update={"terminal_value": Decimal(999)})}
        )
    context.result_store.get_result_for_tenant.return_value = SimpleNamespace(
        analytics_type="TWR" if conflict == "purpose" else COMPOSITE_POOLED_ANALYTICS_TYPE,
        result_status=AsyncResultStatus.FAILED if conflict == "status" else AsyncResultStatus.COMPLETE,
        response_payload=response.model_dump(mode="json"),
    )
    with pytest.raises(APIError) as error:
        application.run_pooled_mwr_attempt(context.job, job_store=context.job_store, settings=context.settings)
    assert error.value.error_code == "INPUT_CUSTODY_CONFLICT"
    context.reader.read_pinned.assert_not_called()
    context.inputs.bind.assert_not_called()


def test_worker_replays_exact_original_without_reopening_supplier(pooled_context):
    context = pooled_context
    response = _response(context)
    context.result_store.get_result_for_tenant.return_value = SimpleNamespace(
        analytics_type=COMPOSITE_POOLED_ANALYTICS_TYPE,
        result_status=AsyncResultStatus.COMPLETE,
        response_payload=response.model_dump(mode="json"),
    )
    replay = application.run_pooled_mwr_attempt(context.job, job_store=context.job_store, settings=context.settings)
    assert replay.model_dump(mode="json") == response.model_dump(mode="json")
    context.reader.read_pinned.assert_not_called()
    context.inputs.bind.assert_not_called()


@pytest.mark.parametrize("conflict", ["missing-original", "observation", "correction-parent"])
def test_publication_refuses_unbound_financial_result_without_inserting(pooled_context, conflict):
    context = pooled_context
    response = _response(context)
    if conflict == "missing-original":
        context.inputs.read_in_transaction.return_value = None
    elif conflict == "observation":
        context.inputs.read_in_transaction.return_value = SimpleNamespace(
            observation=context.observation.model_copy(update={"terminal_value": Decimal(999)}), request=context.request
        )
    else:
        response = response.model_copy(update={"correction_of_calculation_id": uuid4()})
    with pytest.raises(APIError) as error:
        application.publish_pooled_mwr_result(
            context.job,
            response.model_dump(mode="json"),
            job_store=context.job_store,
            result_store=context.result_store,
            settings=context.settings,
        )
    assert error.value.error_code == "INPUT_CUSTODY_CONFLICT"
    context.result_store.record_pooled_success_in_transaction.assert_not_called()


def test_result_correction_cannot_name_its_own_calculation(pooled_context):
    payload = _response(pooled_context).model_dump(mode="json")
    payload["correction_of_calculation_id"] = payload["calculation_id"]
    with pytest.raises(ValidationError, match="new calculation identity"):
        CompositePooledMWRResponse.model_validate(payload)


def test_dependency_refuses_presented_tenant_without_verified_principal():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/performance/composites/analytics",
            "headers": [(b"x-tenant-id", b"controlled-tenant")],
        }
    )
    with pytest.raises(APIError) as error:
        require_pooled_principal(request, tenant_id="controlled-tenant")
    assert error.value.status_code == 403
    assert error.value.error_code == "PRINCIPAL_ADMISSION_DENIED"


@pytest.mark.parametrize("job", [None, SimpleNamespace(analytics_type="TWR")])
def test_read_without_pooled_input_or_pooled_job_has_no_financial_result_access(pooled_context, monkeypatch, job):
    context = pooled_context
    context.inputs.get_member_scope.return_value = None
    jobs = Mock()
    jobs.get_job_for_tenant.return_value = job
    monkeypatch.setattr(application, "compute_job_store", jobs)
    with pytest.raises(APIError) as error:
        application.read_pooled_mwr_result(context.request.calculation_id, principal=context.principal)
    assert error.value.status_code == 404
    context.result_store.get_result_for_tenant.assert_not_called()
    context.reader.read_pinned.assert_not_called()
