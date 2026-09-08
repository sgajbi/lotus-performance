from __future__ import annotations

from uuid import UUID

from app.ports.execution_polling import ExecutionPollingStore
from app.services.async_result_store import AsyncResultRecord, async_result_store
from app.services.compute_job_store import ComputeJobRecord, compute_job_store
from app.services.execution_registry import ExecutionRecord, execution_registry


class DurableExecutionPollingStore:
    """Durable-store adapter for execution polling state reads."""

    def get_execution(self, calculation_id: UUID) -> ExecutionRecord | None:
        return execution_registry.get_execution(calculation_id)

    def get_job(self, calculation_id: UUID, *, tenant_id: str) -> ComputeJobRecord | None:
        return compute_job_store.get_job_for_tenant(calculation_id, tenant_id=tenant_id)

    def get_result(self, calculation_id: UUID, *, tenant_id: str) -> AsyncResultRecord | None:
        return async_result_store.get_result_for_tenant(calculation_id, tenant_id=tenant_id)


execution_polling_store: ExecutionPollingStore = DurableExecutionPollingStore()
