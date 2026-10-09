"""Single owning session, snapshot reads and bounded overlap/dependency admission."""

from contextlib import contextmanager

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_authority.codec import digest, selection_response
from app.adapters.composite_result_authority.records import RevisionRow, ScopeRow
from app.adapters.composite_result_authority.schema import verify_authority_schema
from app.adapters.composite_result_authority.vector import captured_vector, custody_refused
from app.adapters.composite_result_candidate_storage import _require_installed, require_same_result_database
from app.services.composite_metadata_store import _lock_composite_definition_identity, _lock_composite_tenant_identity
from app.services.composite_result_authority.policy import conflict, denied


def require_principal(principal, *, write):
    capability = "operations.runtime.manage" if write else "operations.runtime.read"
    if not isinstance(principal, VerifiedCompositePrincipal) or capability not in principal.capabilities:
        denied()


@contextmanager
def owner_session(owner, results, principal, *, write):
    require_principal(principal, write=write)
    require_same_result_database(owner, results)
    with owner._session() as session:
        dialect = session.bind.dialect.name
        if dialect == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")
        elif not write:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        _require_installed(session.connection())
        verify_authority_schema(session.connection())
        try:
            yield session
        except IntegrityError:
            conflict("Authority persistence refused conflicting workflow content.")


def fence_scopes(session, principal, vectors):
    _lock_composite_tenant_identity(session, principal.tenant_id, exclusive=False)
    for composite in sorted({vector.scope.composite_id for vector in vectors}):
        _lock_composite_definition_identity(
            session, tenant_id=principal.tenant_id, composite_id=composite, exclusive=True
        )


def current_selection(session, tenant, scope_id):
    row = session.get(ScopeRow, (tenant, scope_id))
    if row is None:
        return None
    history = session.get(RevisionRow, (tenant, scope_id, row.revision))
    if history is None:
        custody_refused()
    result = selection_response(history)
    if (
        result.scope.base_id,
        result.scope.period_start,
        result.scope.period_end,
        str(result.bundle_id) if result.bundle_id else None,
    ) != (
        row.base_id,
        row.period_start,
        row.period_end,
        row.bundle_id,
    ):
        custody_refused()
    return result


def overlapping_selections(session, principal, vectors):
    predicates = [
        and_(
            ScopeRow.base_id == vector.scope.base_id,
            ScopeRow.period_start <= vector.scope.period_end,
            ScopeRow.period_end >= vector.scope.period_start,
        )
        for vector in vectors
    ]
    rows = session.scalars(
        select(ScopeRow)
        .where(
            ScopeRow.tenant_id == principal.tenant_id,
            or_(*predicates),
        )
        .order_by(ScopeRow.scope_id)
        .limit(121)
    ).all()
    if len(rows) > 120:
        conflict("The local impact closure exceeds the supported 120-scope bound.")
    return [current_selection(session, principal.tenant_id, row.scope_id) for row in rows]


def dependency_digest(selections):
    return digest({"selections": [selection.model_dump(mode="json") for selection in selections]})


def require_retained_vectors(session, principal, proposal):
    for vector in proposal.targets:
        if captured_vector(session, principal, vector.candidate_id) != vector:
            custody_refused()
