"""Read existing immutable materializations; owns no schema or financial ledger."""

from uuid import UUID

from app.adapters.composite_materialization_repository import (
    CompositeMaterializationStore,
    get_composite_materialization_store,
)
from app.services.composite_materialization.records import MaterializationRecord


class RetainedAnnualDispersionReceiptReader:
    def __init__(self, store: CompositeMaterializationStore | None = None):
        self._store = store

    def get(self, materialization_id: UUID, *, tenant_id: str) -> MaterializationRecord:
        store = self._store if self._store is not None else get_composite_materialization_store()
        return store.get(materialization_id, tenant_id=tenant_id)
