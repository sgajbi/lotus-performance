from typing import Protocol
from uuid import UUID

from app.services.composite_materialization.records import MaterializationRecord


class AnnualDispersionReceiptReader(Protocol):
    def get(self, materialization_id: UUID, *, tenant_id: str) -> MaterializationRecord:
        """Return tenant-scoped evidence after exact publication and source validation."""
        ...
