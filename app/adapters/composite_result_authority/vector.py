"""Reference complete retained financial custody; never calculate authority reads."""

import json

from app.adapters.composite_materialization_records import CompositeMaterializationModel
from app.adapters.composite_materialization_repository import read_retained_record
from app.adapters.composite_result_candidate_records import CompositeResultCandidateModel
from app.adapters.composite_result_candidate_storage import read_candidate
from app.models.composite_authority import authority_digest
from app.models.composite_materialization import CompositeMaterializationState
from app.models.composite_result_authority import AuthorityScope, AuthorityVector, AuthorityWindow
from app.models.composite_result_candidates import CompositeResultCandidateResponse
from app.services.composite_calculation_service import retained_return_method, retained_window_evidence
from app.services.composite_materialization.window_currency_authority import retained_currency_authority
from core.errors import APIError


def absent():
    raise APIError(status_code=404, detail="Authority resource is absent.", error_code="COMPOSITE_AUTHORITY_NOT_FOUND")


def custody_refused():
    raise APIError(
        status_code=503,
        detail="Retained authority custody is unavailable.",
        error_code="COMPOSITE_RESULT_CUSTODY_REFUSED",
    )


def original_candidate(session, principal, candidate_id):
    result = read_candidate(session, tenant_id=principal.tenant_id, candidate_id=candidate_id, principal=principal)
    if result is None:
        absent()
    return CompositeResultCandidateResponse.model_validate(result)


def captured_vector(session, principal, candidate_id):
    original = original_candidate(session, principal, candidate_id)
    row = session.get(CompositeResultCandidateModel, (principal.tenant_id, str(candidate_id)))
    manifest = original.response.selection_manifest
    if row is None or manifest is None:
        custody_refused()
    makers, pins, windows = {row.captured_by}, [], []
    for window in manifest.windows:
        record = _captured_record(session, principal.tenant_id, window.materialization_id)
        source, command = record.source, record.command
        currency = retained_currency_authority(record)
        method = retained_return_method(record, currency.normalization_method)
        if retained_window_evidence(record, method) != window:
            custody_refused()
        pin = {
            "command": command.immutable_payload(),
            "source": source.model_dump(mode="json"),
            "outcomes": [outcome.model_dump(mode="json") for outcome in record.outcomes],
        }
        pins.append(pin)
        windows.append(
            AuthorityWindow(
                period_start=command.period_start,
                period_end=command.period_end,
                materialization_id=command.materialization_id,
                retained_digest=authority_digest(pin),
            )
        )
        makers.update(
            {
                record.actor_id,
                source.definition.created_by,
                source.membership.decided_by,
                source.attestation.attested_by,
            }
        )
    scope = _scope(principal.tenant_id, original)
    vector_digest = authority_digest(
        {
            "tenant_id": principal.tenant_id,
            "scope": scope.model_dump(mode="json"),
            "pins": pins,
            "original_response_digest": row.original_response_digest,
            "calculation_id": row.calculation_id,
            "build_commit": row.build_commit,
            "engine_version": row.engine_version,
            "makers": sorted(makers),
        }
    )
    return AuthorityVector(
        scope=scope,
        candidate_id=candidate_id,
        original_response_digest=row.original_response_digest,
        vector_digest=vector_digest,
        windows=windows,
        maker_subjects=sorted(makers),
    )


def _captured_record(session, tenant, materialization_id):
    retained = session.get(CompositeMaterializationModel, (tenant, str(materialization_id)))
    if retained is None:
        custody_refused()
    record = read_retained_record(retained, session=session)
    if record.state != CompositeMaterializationState.COMPLETE or record.source is None:
        custody_refused()
    return record


def _scope(tenant_id, original):
    response = original.response
    bases = {(period.return_view, period.reporting_currency) for period in response.periods}
    if len(bases) != 1 or response.methodology != "persisted_member_return_asset_weighted_twr_v1":
        custody_refused()
    view, currency = next(iter(bases))
    base = {
        "tenant_id": tenant_id,
        "composite_id": response.composite_id,
        "return_view": view,
        "reporting_currency": currency,
        "method_family": "ASSET_WEIGHTED_COMPOSITE_TWR",
    }
    scoped = {**base, "period_start": response.period_start.isoformat(), "period_end": response.period_end.isoformat()}
    return AuthorityScope(
        scope_id=authority_digest(scoped),
        base_id=authority_digest(base),
        composite_id=response.composite_id,
        period_start=response.period_start,
        period_end=response.period_end,
        return_view=view,
        reporting_currency=currency,
        method_family="ASSET_WEIGHTED_COMPOSITE_TWR",
    )


def require_vector_budget(session, principal, targets):
    count = 0
    for target in targets:
        row = session.get(CompositeResultCandidateModel, (principal.tenant_id, str(target.candidate_id)))
        if row is None:
            absent()
        count += len(json.loads(row.materialization_vector_json))
        if count > 120:
            raise APIError(
                status_code=422,
                detail="Authority bundle exceeds 120 retained windows.",
                error_code="COMPOSITE_AUTHORITY_UNSUPPORTED",
            )
