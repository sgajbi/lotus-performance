"""Atomic original result and descriptor writes in the existing Composite session.

No recalculation occurs when reading a captured original. The descriptor stores
provenance and digests, never a second copy of the financial response.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_candidate_records import CandidateBase, CompositeResultCandidateModel
from app.adapters.composite_result_candidate_schema import candidate_guard_statements
from app.adapters.composite_result_custody_schema import (
    COMPOSITE_CAPTURE_ANALYTICS_TYPE,
    composite_result_custody_guard_statements,
)
from app.adapters.durable_schema.catalog import require_metadata_schema
from app.adapters.durable_schema.guards import require_managed_guards
from app.core.config import get_settings
from app.enterprise_capability_rules import _CAPABILITY_OPERATIONS_RUNTIME_MANAGE
from app.models.composite_authority import authority_digest
from app.models.composites import CompositeTWRRequest, CompositeTWRResponse
from app.services.async_result_store import AsyncResultModel
from app.services.async_result_store import Base as ResultBase
from app.services.calculation_engine_version import calculation_engine_version
from core.errors import APIConflictError, APIError

CAPTURE_CAPABILITY = _CAPABILITY_OPERATIONS_RUNTIME_MANAGE


def _refuse(detail="Retained candidate original result or provenance is unavailable.") -> NoReturn:
    raise APIError(status_code=503, detail=detail, error_code="COMPOSITE_RESULT_CUSTODY_REFUSED", retryable=False)


def _wire(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _wire_digest(wire):
    return "sha256:" + hashlib.sha256(wire.encode()).hexdigest()


def _semantic_response(payload):
    result = copy.deepcopy(payload)
    result.pop("calculation_id")
    result["selection_manifest"].pop("calculation_fingerprint")
    return authority_digest(result)


def _physical_identity(engine):
    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            rows = connection.exec_driver_sql("PRAGMA database_list").all()
            main = next((row[2] for row in rows if row[1] == "main"), None)
            if not main:
                _refuse("Capture requires a shared installed durable database; in-memory authority is unavailable.")
            installed = Path(main).resolve().stat()
            if not installed.st_ino:
                _refuse("Installed SQLite file identity cannot be qualified.")
            return ("sqlite", installed.st_dev, installed.st_ino)
        if connection.dialect.name == "postgresql":
            url = engine.url
            deployed = (url.host, url.port or 5432, url.database)
            actual = tuple(
                connection.execute(
                    text("SELECT current_database(), current_schema(), inet_server_addr()::text, inet_server_port()")
                ).one()
            )
            return ("postgresql", deployed, actual)
    _refuse("Capture database dialect is unsupported.")


def require_same_result_database(composite_store, result_store):
    if _physical_identity(composite_store._engine) != _physical_identity(result_store._engine):
        _refuse("Original result and descriptor must use the same installed owning database.")


def _require_installed(connection):
    require_metadata_schema(connection, ResultBase.metadata)
    require_metadata_schema(connection, CandidateBase.metadata)
    require_managed_guards(
        connection,
        (
            *composite_result_custody_guard_statements(connection.dialect),
            *candidate_guard_statements(connection.dialect),
        ),
    )


def require_release_build():
    build = get_settings().APP_GIT_COMMIT_SHA
    if not re.fullmatch(r"[0-9a-f]{40}", build):
        _refuse("A server-owned release commit is required for original result capture.")
    return build


def _member_ids(response):
    return sorted({member.portfolio_id for period in response.periods for member in period.member_contributions})


def _ready_period(period):
    return (
        period.status == "READY"
        and period.return_value is not None
        and period.cumulative_return is not None
        and not period.reason_codes
    )


def _require_ready_response(response):
    if (
        response.status != "READY"
        or response.cumulative_return is None
        or response.reason_codes
        or not response.periods
    ):
        raise APIConflictError(
            "Capture requires a complete READY response.", error_code="COMPOSITE_CAPTURE_EVIDENCE_INCOMPLETE"
        )
    if not all(_ready_period(period) for period in response.periods):
        raise APIConflictError(
            "Capture requires complete READY periods.", error_code="COMPOSITE_CAPTURE_EVIDENCE_INCOMPLETE"
        )


def _require_request_binding(request, response):
    manifest = response.selection_manifest
    if not request.materialization_ids or manifest is None:
        raise APIConflictError(
            "Capture requires an explicit retained vector.", error_code="COMPOSITE_CAPTURE_EVIDENCE_INCOMPLETE"
        )
    actual = (
        response.calculation_id,
        response.composite_id,
        response.period_start,
        response.period_end,
        [window.materialization_id for window in manifest.windows],
        manifest.engine_version,
    )
    expected = (
        request.calculation_id,
        request.composite_id,
        request.period_start,
        request.period_end,
        request.materialization_ids,
        calculation_engine_version(),
    )
    if actual != expected:
        raise APIConflictError(
            "Capture requires the response for its exact retained vector.",
            error_code="COMPOSITE_CAPTURE_EVIDENCE_INCOMPLETE",
        )
    return manifest


def _admit(request, response, principal):
    build = require_release_build()
    if not isinstance(principal, VerifiedCompositePrincipal) or CAPTURE_CAPABILITY not in principal.capabilities:
        raise APIError(
            status_code=403,
            detail="Verified capture capability is required.",
            error_code="COMPOSITE_CAPTURE_CAPABILITY_REQUIRED",
        )
    request = CompositeTWRRequest.model_validate(request.model_dump(mode="json"))
    response = CompositeTWRResponse.model_validate(response.model_dump(mode="json"))
    _require_ready_response(response)
    manifest = _require_request_binding(request, response)
    if not set(_member_ids(response)) <= principal.portfolio_scope:
        raise APIError(
            status_code=403, detail="Capture portfolio scope is refused.", error_code="PORTFOLIO_OUTSIDE_SCOPE"
        )
    semantic = request.model_dump(mode="json")
    semantic.pop("calculation_id")
    semantic.update(
        tenant_id=principal.tenant_id,
        build_commit=build,
        engine_version=manifest.engine_version,
        methodology=response.methodology,
    )
    return request, response, build, authority_digest(semantic)


def _retained_member_scope(row):
    try:
        members = json.loads(row.member_scope_json)
        if not isinstance(members, list) or not members or not all(isinstance(value, str) for value in members):
            _refuse()
        if members != sorted(set(members)):
            _refuse()
        return members
    except (ValueError, TypeError):
        _refuse()


def _retained_original(session, row):
    original = session.get(AsyncResultModel, row.calculation_id)
    if original is None or not original.response_json:
        _refuse()
    actual = (
        original.tenant_id,
        original.analytics_type,
        original.result_status,
        original.error_message,
        original.error_type,
        original.failure_json,
        _wire_digest(original.response_json),
    )
    expected = (
        row.tenant_id,
        COMPOSITE_CAPTURE_ANALYTICS_TYPE,
        "complete",
        None,
        None,
        None,
        row.original_response_digest,
    )
    if actual != expected:
        _refuse()
    return original.response_json


def _retained_response(wire, row, members):
    try:
        payload = json.loads(wire)
        response = CompositeTWRResponse.model_validate(payload)
        manifest = response.selection_manifest
        if manifest is None:
            _refuse()
        actual = (
            str(response.calculation_id),
            response.composite_id,
            response.methodology,
            manifest.engine_version,
            _wire([str(window.materialization_id) for window in manifest.windows]),
            _semantic_response(payload),
            _member_ids(response),
        )
        expected = (
            row.calculation_id,
            row.composite_id,
            row.methodology,
            row.engine_version,
            row.materialization_vector_json,
            row.semantic_response_digest,
            members,
        )
        if actual != expected:
            _refuse()
        _require_ready_response(response)
        return payload
    except (ValueError, TypeError, KeyError, APIConflictError):
        _refuse()


def _candidate_receipt(row, payload):
    return {
        "candidate_id": row.candidate_id,
        "qualification": "CALCULATED_RESULT_CANDIDATE",
        "tenant_id": row.tenant_id,
        "original_response_digest": row.original_response_digest,
        "build_commit": row.build_commit,
        "engine_version": row.engine_version,
        "captured_by": row.captured_by,
        "principal_kind": row.principal_kind,
        "delegated_actor": row.delegated_actor,
        "credential_id": row.credential_id,
        "captured_at_utc": row.captured_at_utc,
        "response": payload,
    }


def read_candidate(session, *, tenant_id, candidate_id, principal=None):
    row = session.get(CompositeResultCandidateModel, (tenant_id, str(candidate_id)))
    if row is None:
        return None
    members = _retained_member_scope(row)
    if principal is not None and not set(members) <= principal.portfolio_scope:
        raise APIError(
            status_code=403, detail="Candidate portfolio scope is refused.", error_code="PORTFOLIO_OUTSIDE_SCOPE"
        )
    return _candidate_receipt(row, _retained_response(_retained_original(session, row), row, members))


def _existing_candidate(session, tenant, candidate_id, digest):
    existing = session.get(CompositeResultCandidateModel, (tenant, str(candidate_id)))
    if existing is not None:
        return existing
    return session.execute(
        select(CompositeResultCandidateModel).where(
            CompositeResultCandidateModel.tenant_id == tenant,
            CompositeResultCandidateModel.semantic_request_digest == digest,
        )
    ).scalar_one_or_none()


def capture_candidate(session, *, candidate_id: UUID, request, response, principal):
    request, response, build, digest = _admit(request, response, principal)
    _require_installed(session.connection())
    payload = response.model_dump(mode="json")
    original_wire = _wire(payload)
    financial_digest = _semantic_response(payload)
    tenant = principal.tenant_id
    existing = _existing_candidate(session, tenant, candidate_id, digest)
    if existing is not None:
        return _same_candidate(session, existing, digest, financial_digest)
    if session.get(AsyncResultModel, str(request.calculation_id)) is not None:
        raise APIConflictError(
            "Original calculation identity is already retained.", error_code="COMPOSITE_CAPTURE_IDENTITY_CONFLICT"
        )
    now = datetime.now(UTC)
    row = CompositeResultCandidateModel(
        tenant_id=tenant,
        candidate_id=str(candidate_id),
        calculation_id=str(request.calculation_id),
        composite_id=request.composite_id,
        semantic_request_digest=digest,
        semantic_response_digest=financial_digest,
        original_response_digest=_wire_digest(original_wire),
        build_commit=build,
        engine_version=response.selection_manifest.engine_version,
        methodology=response.methodology,
        materialization_vector_json=_wire([str(value) for value in request.materialization_ids]),
        member_scope_json=_wire(_member_ids(response)),
        captured_by=principal.subject,
        principal_kind=principal.principal_kind,
        credential_id=principal.credential_id,
        delegated_actor=principal.delegated_actor,
        captured_at_utc=now.isoformat(),
    )
    try:
        with session.begin_nested():
            session.add(
                AsyncResultModel(
                    calculation_id=str(request.calculation_id),
                    tenant_id=tenant,
                    analytics_type=COMPOSITE_CAPTURE_ANALYTICS_TYPE,
                    result_status="complete",
                    response_json=original_wire,
                    created_at_utc=now,
                    updated_at_utc=now,
                )
            )
            session.flush()
            session.add(row)
            session.flush()
    except IntegrityError as exc:
        winner = session.execute(
            select(CompositeResultCandidateModel).where(
                CompositeResultCandidateModel.tenant_id == tenant,
                CompositeResultCandidateModel.semantic_request_digest == digest,
            )
        ).scalar_one_or_none()
        if winner is None:
            raise APIConflictError(
                "Candidate identity collides with different retained content.",
                error_code="COMPOSITE_CAPTURE_IDENTITY_CONFLICT",
            ) from exc
        return _same_candidate(session, winner, digest, financial_digest)
    return read_candidate(session, tenant_id=tenant, candidate_id=candidate_id)


def _same_candidate(session, row, digest, financial_digest):
    if row.semantic_request_digest != digest or row.semantic_response_digest != financial_digest:
        raise APIConflictError(
            "Candidate identity contradicts original retained content.",
            error_code="COMPOSITE_CAPTURE_IDENTITY_CONFLICT",
        )
    return read_candidate(session, tenant_id=row.tenant_id, candidate_id=row.candidate_id)
