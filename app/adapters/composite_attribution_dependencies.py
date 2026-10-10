"""Revalidate exact originals and optional live selection in the owning transaction."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.composite_result_authority.context import current_selection
from app.adapters.composite_result_authority.records import ScopeRow
from app.adapters.composite_result_authority.schema import authority_guard_statements
from app.adapters.composite_result_authority.vector import captured_vector, original_candidate
from app.adapters.composite_result_candidate_schema import candidate_guard_statements
from app.adapters.composite_result_custody_schema import composite_result_custody_guard_statements
from app.adapters.durable_schema.guards import require_managed_guards
from app.services.composite_attribution.source_binding import refuse
from app.services.composite_metadata_store import _lock_composite_definition_identity


def retained_dependencies(connection, request, principal, *, require_current=True):
    """Session borrows the active job Connection and cannot own its commit."""
    # Full metadata verification belongs to read-only startup/owner verification.
    # Within the existing SELECT/INSERT-only lease fence, inspect exact guards
    # through catalog SELECTs; ORM queries themselves require every consumed column.
    require_managed_guards(
        connection,
        (
            *candidate_guard_statements(connection.dialect),
            *composite_result_custody_guard_statements(connection.dialect),
        ),
    )
    with Session(bind=connection, join_transaction_mode="rollback_only") as session:
        _lock_composite_definition_identity(
            session, tenant_id=principal.tenant_id, composite_id=request.composite_id, exclusive=False
        )
        original = original_candidate(session, principal, request.candidate_id)
        vector = captured_vector(session, principal, request.candidate_id)
        if request.official_scope_id is not None and require_current:
            require_managed_guards(connection, authority_guard_statements(connection.dialect))
            session.execute(
                select(ScopeRow)
                .where(ScopeRow.tenant_id == principal.tenant_id, ScopeRow.scope_id == request.official_scope_id)
                .with_for_update()
            )
            current = current_selection(session, principal.tenant_id, request.official_scope_id)
            if (
                current is None
                or current.revision != request.official_revision
                or current.current_use != "SELECTED"
                or current.candidate_id != request.candidate_id
                or current.vector_digest != vector.vector_digest
            ):
                refuse("OFFICIAL_SELECTION_STALE", "Exact requested current selection is stale, withdrawn or replaced.")
        return original, vector
