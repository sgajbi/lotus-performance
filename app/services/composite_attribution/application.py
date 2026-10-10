"""Existing durable execution with purpose-scoped original attribution custody."""

from uuid import UUID

from app.adapters.composite_attribution_dependencies import retained_dependencies
from app.adapters.composite_attribution_deployment import get_composite_attribution_deployment
from app.adapters.composite_attribution_repository import bind_attribution_input, read_attribution_input
from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_custody_schema import COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE
from app.models.composite_attribution import (
    CompositeAttributionAcceptedResponse,
    CompositeAttributionRequest,
    CompositeAttributionResponse,
)
from app.observability import tenant_id_var
from app.ports.composite_attribution import AttributionAdmissionError
from app.services.async_result_service import resolve_async_result
from app.services.async_result_store import AsyncResultStatus, get_async_result_store
from app.services.calculation_engine_version import calculation_engine_version
from app.services.composite_attribution.admission import admit_attribution
from app.services.composite_attribution.kernel_adapter import calculate_attribution
from app.services.composite_metadata_store import get_composite_metadata_store
from app.services.compute_job_store import compute_job_store
from app.services.reproducibility_service import generate_value_fingerprint
from app.services.submission_fencing_service import register_async_submission_or_raise
from core.attribution_precision_policy import require_attribution_precision
from core.errors import APIConflictError, APIError, APINotFoundError


def accepted_attribution(calculation_id: UUID):
    return CompositeAttributionAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/composites/analytics/results/{calculation_id}",
    )


def require_member_scope(members, principal):
    if (
        not isinstance(members, (tuple, list))
        or not members
        or any(not isinstance(value, str) or not value for value in members)
        or len(set(members)) != len(members)
    ):
        raise APIConflictError(
            "Complete attribution population scope is unavailable.", error_code="MISSING_POPULATION_COVERAGE"
        )
    if not set(members) <= principal.portfolio_scope:
        raise APIError(
            status_code=403, detail="Attribution member scope is refused.", error_code="PORTFOLIO_OUTSIDE_SCOPE"
        )


def source_error(error):
    unavailable = error.code.endswith("UNAVAILABLE")
    return APIError(status_code=503 if unavailable else 409, detail=str(error), error_code=error.code, retryable=False)


def principal_payload(principal):
    return {
        "principal_kind": principal.principal_kind,
        "subject": principal.subject,
        "tenant_id": principal.tenant_id,
        "capabilities": sorted(principal.capabilities),
        "portfolio_scope": sorted(principal.portfolio_scope),
        "credential_id": principal.credential_id,
        "delegated_actor": principal.delegated_actor,
    }


def job_principal(job):
    payload = dict(job.request_payload["admitted_principal"])
    payload["capabilities"] = frozenset(payload["capabilities"])
    payload["portfolio_scope"] = frozenset(payload["portfolio_scope"])
    principal = VerifiedCompositePrincipal(**payload)
    if principal.tenant_id != job.tenant_id:
        raise APIConflictError("Job tenant differs from admitted principal.", error_code="INPUT_CUSTODY_CONFLICT")
    require_member_scope(job.request_payload["admitted_portfolio_scope"], principal)
    return principal


def submit_attribution(request, *, principal):
    # Strict unsupported precision refuses before source reads, originals or jobs.
    require_attribution_precision(request.precision_mode)
    existing = compute_job_store.get_job_for_tenant(request.calculation_id, tenant_id=principal.tenant_id)
    try:
        members = (
            existing.request_payload.get("admitted_portfolio_scope")
            if existing is not None
            else get_composite_attribution_deployment().source.read_population_scope(
                request, tenant_id=principal.tenant_id
            )
        )
        require_member_scope(members, principal)
        if existing is not None and (
            existing.analytics_type != COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE
            or existing.request_payload.get("request") != request.model_dump(mode="json")
        ):
            raise APIConflictError("Calculation binds another original request.", error_code="INPUT_CUSTODY_CONFLICT")
        _require_correction(request, principal)
        owner = get_composite_metadata_store()
        with owner._session() as session:
            retained_dependencies(session.connection(), request, principal, require_current=existing is None)
    except AttributionAdmissionError as exc:
        raise source_error(exc) from exc
    payload = {
        "request": request.model_dump(mode="json"),
        "admitted_portfolio_scope": sorted(members),
        "admitted_principal": principal_payload(principal),
    }
    fingerprint, calculation_hash = generate_value_fingerprint(payload, calculation_engine_version())
    token = tenant_id_var.set(principal.tenant_id)
    try:
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type=COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE,
            portfolio_id=None,
            requested_window={"start_date": str(request.period_start), "end_date": str(request.period_end)},
            input_fingerprint=fingerprint,
            calculation_hash=calculation_hash,
            request_payload=payload,
            offload_reason="composite_single_period_brinson_fachler",
            requires_tenant_authority=True,
            accepted_response_factory=accepted_attribution,
        )
    finally:
        tenant_id_var.reset(token)


def _require_correction(request, principal):
    if request.correction_of_calculation_id is None:
        return
    original = compute_job_store.get_job_for_tenant(request.correction_of_calculation_id, tenant_id=principal.tenant_id)
    if original is None or original.analytics_type != COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE:
        raise APINotFoundError("Original attribution calculation is absent in the verified tenant.")
    require_member_scope(original.request_payload.get("admitted_portfolio_scope"), principal)
    previous = CompositeAttributionRequest.model_validate(original.request_payload["request"])
    fields = ("composite_id", "period_start", "period_end", "reporting_currency", "return_view", "method")
    if any(getattr(previous, key) != getattr(request, key) for key in fields):
        raise APIConflictError(
            "Correction differs from the original analytical scope.", error_code="CORRECTION_SCOPE_CONFLICT"
        )


def attribution_claim(job):
    return dict(
        calculation_id=job.calculation_id,
        tenant_id=job.tenant_id,
        analytics_type=COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE,
        worker_id=job.worker_id,
        expected_attempt_count=job.attempt_count + 1,
    )


def run_attribution_attempt(job, *, job_store, settings):
    request = CompositeAttributionRequest.model_validate(job.request_payload["request"])
    require_attribution_precision(request.precision_mode)
    if request.calculation_id != job.calculation_id:
        raise APIConflictError("Job and original calculation identities differ.", error_code="INPUT_CUSTODY_CONFLICT")
    principal = job_principal(job)
    claim = attribution_claim(job)
    try:
        snapshot = job_store.run_with_active_lease_transaction(
            **claim,
            operation=lambda connection: read_attribution_input(connection, job.calculation_id, principal=principal),
        )
        if snapshot is None:
            deployment = get_composite_attribution_deployment()
            bundle = deployment.source.read_pinned(request, tenant_id=job.tenant_id)
            if set(bundle.expected_portfolio_ids) != set(job.request_payload["admitted_portfolio_scope"]):
                raise APIConflictError(
                    "Financial source differs from admitted population.", error_code="SOURCE_CUT_CONFLICT"
                )
            approval = deployment.authority.verify(request, bundle)
            owner = get_composite_metadata_store(database_url=settings.LINEAGE_METADATA_DATABASE_URL)
            with owner._session() as session:
                original, vector = retained_dependencies(session.connection(), request, principal)
            observation = admit_attribution(
                request, bundle, approval, tenant_id=job.tenant_id, original=original, vector=vector
            )
            snapshot = job_store.run_with_active_lease_transaction(
                **claim,
                operation=lambda connection: bind_attribution_input(
                    connection, request, observation, principal=principal
                ),
            )
        elif snapshot.request != request:
            raise APIConflictError(
                "Retained request differs from queued attribution.", error_code="INPUT_CUSTODY_CONFLICT"
            )
    except AttributionAdmissionError as exc:
        raise source_error(exc) from exc
    retained = get_async_result_store(database_url=settings.LINEAGE_METADATA_DATABASE_URL).get_result_for_tenant(
        job.calculation_id, tenant_id=job.tenant_id
    )
    if retained is not None:
        return _replay_retained_result(request, snapshot, retained)
    return build_attribution_response(
        request, snapshot.observation, engine_version=calculation_engine_version(settings)
    )


def build_attribution_response(request, observation, *, engine_version):
    """Assemble the financial response from admitted original observations."""
    fingerprint, calculation_hash = financial_identity(request, observation, engine_version)
    return CompositeAttributionResponse(
        calculation_id=request.calculation_id,
        composite_id=request.composite_id,
        input_manifest_digest=observation.input_manifest_digest,
        calculation_engine_version=engine_version,
        financial_input_fingerprint=fingerprint,
        calculation_hash=calculation_hash,
        official_scope_id=request.official_scope_id,
        official_revision=request.official_revision,
        correction_of_calculation_id=request.correction_of_calculation_id,
        observation=observation,
        outcome=calculate_attribution(request, observation),
    )


def _replay_retained_result(request, snapshot, retained):
    if (
        retained.analytics_type != COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE
        or retained.result_status != AsyncResultStatus.COMPLETE
    ):
        raise APIConflictError("Retained result purpose differs.", error_code="INPUT_CUSTODY_CONFLICT")
    response = CompositeAttributionResponse.model_validate(retained.response_payload)
    _require_result_original(response, snapshot)
    _require_financial_identity(request, response)
    return response


def _require_result_original(response, snapshot):
    if (
        response.calculation_id != snapshot.request.calculation_id
        or response.composite_id != snapshot.request.composite_id
        or response.correction_of_calculation_id != snapshot.request.correction_of_calculation_id
        or response.input_manifest_digest != snapshot.observation.input_manifest_digest
        or response.observation != snapshot.observation
        or response.official_scope_id != snapshot.request.official_scope_id
        or response.official_revision != snapshot.request.official_revision
    ):
        raise APIConflictError(
            "Retained result differs from original attribution evidence.", error_code="INPUT_CUSTODY_CONFLICT"
        )


def publish_attribution_result(job, response_payload, *, job_store, result_store, settings):
    response = CompositeAttributionResponse.model_validate(response_payload)
    principal = job_principal(job)
    request = CompositeAttributionRequest.model_validate(job.request_payload["request"])
    _require_financial_identity(request, response)
    _require_effects(request, response)
    try:
        verified = get_composite_attribution_deployment().authority.verify(request, response.observation.source_bundle)
    except AttributionAdmissionError as exc:
        raise source_error(exc) from exc
    if verified != response.observation.approval:
        raise APIConflictError(
            "Financial-purpose authority changed before publication.",
            error_code="ATTRIBUTION_PURPOSE_APPROVAL_CONFLICT",
        )

    def publish(connection):
        snapshot = read_attribution_input(connection, job.calculation_id, principal=principal)
        if snapshot is None:
            raise APIConflictError("Original attribution input is absent.", error_code="INPUT_CUSTODY_CONFLICT")
        retained_dependencies(connection, snapshot.request, principal)
        _require_result_original(response, snapshot)
        result_store.record_attribution_success_in_transaction(
            connection,
            calculation_id=job.calculation_id,
            tenant_id=job.tenant_id,
            input_manifest_digest=snapshot.observation.input_manifest_digest,
            response_payload=response_payload,
        )

    try:
        job_store.run_with_active_lease_transaction(**attribution_claim(job), operation=publish)
    except AttributionAdmissionError as exc:
        raise source_error(exc) from exc


def read_attribution_result(calculation_id, *, principal):
    job = compute_job_store.get_job_for_tenant(calculation_id, tenant_id=principal.tenant_id)
    if job is None or job.analytics_type != COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE:
        raise APINotFoundError("Attribution calculation is absent in the verified tenant.")
    require_member_scope(job.request_payload.get("admitted_portfolio_scope"), principal)
    token = tenant_id_var.set(principal.tenant_id)
    try:
        result = resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type=COMPOSITE_ATTRIBUTION_ANALYTICS_TYPE,
            response_model=CompositeAttributionResponse,
            accepted_response_factory=accepted_attribution,
            not_found_detail="Attribution calculation is absent in the verified tenant.",
            failed_detail="Composite attribution failed.",
        )
        if isinstance(result, CompositeAttributionResponse):
            _require_financial_identity(
                CompositeAttributionRequest.model_validate(job.request_payload["request"]), result
            )
            with get_composite_metadata_store()._session() as session:
                snapshot = read_attribution_input(session.connection(), calculation_id, principal=principal)
                if snapshot is None:
                    raise APIConflictError(
                        "Original attribution custody is absent.", error_code="INPUT_CUSTODY_CONFLICT"
                    )
                _require_result_original(result, snapshot)
        return result
    except AttributionAdmissionError as exc:
        raise source_error(exc) from exc
    finally:
        tenant_id_var.reset(token)


def _require_effects(request, response):
    """Numerical verification stays outside the active job write transaction."""
    if response.outcome != calculate_attribution(request, response.observation):
        raise APIConflictError(
            "Effects differ from the original observed economics.", error_code="INPUT_CUSTODY_CONFLICT"
        )


def financial_identity(request, observation, engine_version):
    """Full original financial identity; the request admission hash is separate."""
    return generate_value_fingerprint(
        {"request": request.model_dump(mode="json"), "observation": observation.model_dump(mode="json")}, engine_version
    )


def _require_financial_identity(request, response):
    fingerprint, calculation_hash = financial_identity(
        request, response.observation, response.calculation_engine_version
    )
    if (response.financial_input_fingerprint, response.calculation_hash) != (fingerprint, calculation_hash):
        raise APIConflictError(
            "Financial fingerprint differs from its complete retained evidence.", error_code="INPUT_CUSTODY_CONFLICT"
        )
