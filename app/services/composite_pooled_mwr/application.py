"""Existing asynchronous lifecycle with immutable source and result custody."""

from uuid import UUID

from app.adapters.composite_pooled_mwr_repository import get_composite_pooled_mwr_input_store
from app.adapters.composite_pooled_mwr_source import get_pooled_monetary_source_reader
from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_custody_schema import COMPOSITE_POOLED_ANALYTICS_TYPE
from app.models.composite_pooled_mwr import (
    CompositePooledMWRAcceptedResponse,
    CompositePooledMWRRequest,
    CompositePooledMWRResponse,
)
from app.observability import tenant_id_var
from app.ports.composite_pooled_mwr import PooledSourceAdmissionError
from app.services.async_result_service import resolve_async_result
from app.services.async_result_store import AsyncResultStatus, get_async_result_store
from app.services.calculation_engine_version import calculation_engine_version
from app.services.composite_pooled_mwr.admission import admit_pooled_observation
from app.services.composite_pooled_mwr.solver_adapter import calculate_pooled_xirr
from app.services.composite_pooled_mwr.source_binding import require_pooled_day_basis
from app.services.compute_job_store import compute_job_store
from app.services.reproducibility_service import generate_value_fingerprint
from app.services.submission_fencing_service import register_async_submission_or_raise
from core.errors import APIConflictError, APIError, APINotFoundError


def accepted_pooled_mwr(calculation_id: UUID) -> CompositePooledMWRAcceptedResponse:
    return CompositePooledMWRAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/composites/analytics/results/{calculation_id}",
    )


def _require_member_scope(members, principal):
    if (
        not isinstance(members, (tuple, list))
        or not members
        or any(not isinstance(member, str) or not member for member in members)
        or len(set(members)) != len(members)
    ):
        raise APIConflictError("Complete population scope is unavailable.", error_code="MISSING_POPULATION_COVERAGE")
    if not set(members) <= principal.portfolio_scope:
        raise APIError(status_code=403, detail="Pooled member scope is refused.", error_code="PORTFOLIO_OUTSIDE_SCOPE")


def _source_error(error: PooledSourceAdmissionError) -> APIConflictError:
    return APIConflictError(str(error), error_code=error.code)


def submit_pooled_mwr(request: CompositePooledMWRRequest, *, principal: VerifiedCompositePrincipal):
    inputs = get_composite_pooled_mwr_input_store()
    try:
        require_pooled_day_basis(request)
        retained_members = inputs.get_member_scope(request.calculation_id, tenant_id=principal.tenant_id)
        members = (
            retained_members
            if retained_members is not None
            else get_pooled_monetary_source_reader().read_population_scope(request, tenant_id=principal.tenant_id)
        )
    except PooledSourceAdmissionError as exc:
        raise _source_error(exc) from exc
    _require_member_scope(members, principal)
    if retained_members is not None:
        existing_snapshot = inputs.get(request.calculation_id, tenant_id=principal.tenant_id)
        if existing_snapshot is None or existing_snapshot.request != request:
            raise APIConflictError("Retained original binds a different request.", error_code="INPUT_CUSTODY_CONFLICT")
    if request.correction_of_calculation_id is not None:
        _require_correction_scope(request, principal, inputs)
    payload = {"request": request.model_dump(mode="json"), "admitted_portfolio_scope": sorted(members)}
    fingerprint, calculation_hash = generate_value_fingerprint(payload, calculation_engine_version())
    token = tenant_id_var.set(principal.tenant_id)
    try:
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type=COMPOSITE_POOLED_ANALYTICS_TYPE,
            portfolio_id=None,
            requested_window={"start_date": str(request.period_start), "end_date": str(request.period_end)},
            input_fingerprint=fingerprint,
            calculation_hash=calculation_hash,
            request_payload=payload,
            offload_reason="pooled_composite_xirr",
            requires_tenant_authority=True,
            accepted_response_factory=accepted_pooled_mwr,
        )
    finally:
        tenant_id_var.reset(token)


def _require_correction_scope(request, principal, inputs):
    original_id = request.correction_of_calculation_id
    members = inputs.get_member_scope(original_id, tenant_id=principal.tenant_id)
    if members is None:
        raise APINotFoundError("Original pooled calculation is absent in the verified tenant.")
    _require_member_scope(members, principal)
    original_snapshot = inputs.get(original_id, tenant_id=principal.tenant_id)
    if original_snapshot is None:
        raise APIConflictError("Original custody is unavailable.", error_code="INPUT_CUSTODY_CONFLICT")
    original = original_snapshot.request
    if any(
        getattr(request, name) != getattr(original, name)
        for name in ("composite_id", "period_start", "period_end", "reporting_currency", "return_view", "method")
    ):
        raise APIConflictError(
            "Correction differs from the original analytical scope.", error_code="CORRECTION_SCOPE_CONFLICT"
        )


def pooled_claim(job) -> dict:
    """Capture the acquired attempt from the queued record, never re-read a newer claim."""
    return dict(
        calculation_id=job.calculation_id,
        tenant_id=job.tenant_id,
        analytics_type=COMPOSITE_POOLED_ANALYTICS_TYPE,
        worker_id=job.worker_id,
        expected_attempt_count=job.attempt_count + 1,
    )


def run_pooled_mwr_attempt(job, *, job_store, settings) -> CompositePooledMWRResponse:
    request = CompositePooledMWRRequest.model_validate(job.request_payload["request"])
    if request.calculation_id != job.calculation_id:
        raise APIConflictError("Job and request calculation identities differ.", error_code="INPUT_CUSTODY_CONFLICT")
    inputs = get_composite_pooled_mwr_input_store(database_url=settings.LINEAGE_METADATA_DATABASE_URL)
    claim = pooled_claim(job)
    try:
        snapshot = job_store.run_with_active_lease_transaction(
            **claim,
            operation=lambda connection: inputs.read_in_transaction(
                connection, job.calculation_id, tenant_id=job.tenant_id
            ),
        )
        if snapshot is None:
            bundle = get_pooled_monetary_source_reader().read_pinned(request, tenant_id=job.tenant_id)
            if set(bundle.expected_portfolio_ids) != set(job.request_payload["admitted_portfolio_scope"]):
                raise APIConflictError(
                    "Source population differs from admitted scope.", error_code="SOURCE_CUT_CONFLICT"
                )
            observation = admit_pooled_observation(request, bundle, tenant_id=job.tenant_id)
            snapshot = job_store.run_with_active_lease_transaction(
                **claim,
                operation=lambda connection: inputs.bind(
                    connection, tenant_id=job.tenant_id, request=request, observation=observation
                ),
            )
        elif snapshot.request != request:
            raise APIConflictError("Retained input differs from queued request.", error_code="INPUT_CUSTODY_CONFLICT")
    except PooledSourceAdmissionError as exc:
        raise _source_error(exc) from exc
    replay = _retained_pooled_result(job, snapshot, settings)
    if replay is not None:
        return replay
    return CompositePooledMWRResponse(
        calculation_id=job.calculation_id,
        composite_id=request.composite_id,
        input_manifest_digest=snapshot.observation.input_manifest_digest,
        calculation_engine_version=calculation_engine_version(settings),
        correction_of_calculation_id=request.correction_of_calculation_id,
        observation=snapshot.observation,
        outcome=calculate_pooled_xirr(request, snapshot.observation),
    )


def _retained_pooled_result(job, snapshot, settings):
    retained = get_async_result_store(database_url=settings.LINEAGE_METADATA_DATABASE_URL).get_result_for_tenant(
        job.calculation_id, tenant_id=job.tenant_id
    )
    if retained is not None:
        if (
            retained.analytics_type != COMPOSITE_POOLED_ANALYTICS_TYPE
            or retained.result_status != AsyncResultStatus.COMPLETE
        ):
            raise APIConflictError("Retained result purpose differs.", error_code="INPUT_CUSTODY_CONFLICT")
        response = CompositePooledMWRResponse.model_validate(retained.response_payload)
        if response.observation != snapshot.observation:
            raise APIConflictError("Retained result differs from original inputs.", error_code="INPUT_CUSTODY_CONFLICT")
        return response
    return None


def publish_pooled_mwr_result(job, response_payload, *, job_store, result_store, settings) -> None:
    response = CompositePooledMWRResponse.model_validate(response_payload)
    inputs = get_composite_pooled_mwr_input_store(database_url=settings.LINEAGE_METADATA_DATABASE_URL)

    def publish(connection):
        snapshot = inputs.read_in_transaction(connection, job.calculation_id, tenant_id=job.tenant_id)
        if (
            snapshot is None
            or snapshot.observation != response.observation
            or snapshot.request.correction_of_calculation_id != response.correction_of_calculation_id
        ):
            raise APIConflictError("Result differs from retained original inputs.", error_code="INPUT_CUSTODY_CONFLICT")
        result_store.record_pooled_success_in_transaction(
            connection,
            calculation_id=job.calculation_id,
            tenant_id=job.tenant_id,
            input_manifest_digest=snapshot.observation.input_manifest_digest,
            response_payload=response_payload,
        )

    job_store.run_with_active_lease_transaction(**pooled_claim(job), operation=publish)


def read_pooled_mwr_result(calculation_id: UUID, *, principal: VerifiedCompositePrincipal):
    inputs = get_composite_pooled_mwr_input_store()
    members = inputs.get_member_scope(calculation_id, tenant_id=principal.tenant_id)
    if members is None:
        job = compute_job_store.get_job_for_tenant(calculation_id, tenant_id=principal.tenant_id)
        if job is None or job.analytics_type != COMPOSITE_POOLED_ANALYTICS_TYPE:
            raise APINotFoundError("Pooled calculation is absent in the verified tenant.")
        members = job.request_payload.get("admitted_portfolio_scope")
    _require_member_scope(members, principal)
    token = tenant_id_var.set(principal.tenant_id)
    try:
        return resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type=COMPOSITE_POOLED_ANALYTICS_TYPE,
            response_model=CompositePooledMWRResponse,
            accepted_response_factory=accepted_pooled_mwr,
            not_found_detail="Pooled result is absent in the verified tenant.",
            failed_detail="Pooled computation failed.",
        )
    finally:
        tenant_id_var.reset(token)
