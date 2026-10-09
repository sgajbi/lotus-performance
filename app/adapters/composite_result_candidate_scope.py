"""Read retained membership metadata before accessing original numerical facts."""

import json

from sqlalchemy import func, literal_column, select
from sqlalchemy.exc import DBAPIError

from app.adapters.composite_materialization_records import CompositeMaterializationModel
from core.errors import APIConflictError, APIError


def _member_scope(scope_json):
    try:
        members = json.loads(scope_json)
        if (
            not isinstance(members, list)
            or not members
            or not all(isinstance(value, str) and value for value in members)
        ):
            raise ValueError("Invalid retained member identity scope")
        if len(set(members)) != len(members):
            raise ValueError("Duplicate retained members")
        return set(members)
    except (ValueError, TypeError, KeyError):
        raise APIError(
            status_code=503,
            detail="Retained member scope is unavailable.",
            error_code="COMPOSITE_RESULT_CUSTODY_REFUSED",
        ) from None


def _require_complete_window(row):
    if row is None or row.state != "COMPLETE":
        raise APIConflictError(
            "A complete retained window is required.", error_code="COMPOSITE_CAPTURE_EVIDENCE_INCOMPLETE"
        )


def _scope_projection(connection):
    if connection.dialect.name == "postgresql":
        return literal_column("source_json::jsonb #>> '{attestation,expected_portfolio_ids}'").label("member_scope")
    return func.json_extract(CompositeMaterializationModel.source_json, "$.attestation.expected_portfolio_ids").label(
        "member_scope"
    )


def _scope_row(connection, identity, tenant):
    try:
        return connection.execute(
            select(
                CompositeMaterializationModel.state,
                _scope_projection(connection),
            ).where(
                CompositeMaterializationModel.tenant_id == tenant,
                CompositeMaterializationModel.materialization_id == str(identity),
            )
        ).one_or_none()
    except DBAPIError:
        raise APIError(
            status_code=503,
            detail="Retained member scope is unavailable.",
            error_code="COMPOSITE_RESULT_CUSTODY_REFUSED",
        ) from None


def require_candidate_member_scope(store, *, request, principal):
    # Project only member identities inside the database, not the full source
    # JSON (which may also contain FX inputs). Numerical payloads stay unread.
    with store._engine.connect() as connection:
        for identity in request.materialization_ids:
            row = _scope_row(connection, identity, principal.tenant_id)
            _require_complete_window(row)
            if not _member_scope(row.member_scope) <= principal.portfolio_scope:
                raise APIError(
                    status_code=403, detail="Retained member scope is refused.", error_code="PORTFOLIO_OUTSIDE_SCOPE"
                )
