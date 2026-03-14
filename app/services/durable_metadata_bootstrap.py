from __future__ import annotations

from app.services.async_result_store import AsyncResultStore, async_result_store
from app.services.compute_job_store import ComputeJobStore, compute_job_store
from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.lineage_metadata_store import LineageMetadataStore, lineage_metadata_store


def bootstrap_durable_metadata_stores(
    *,
    execution_store: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry] = execution_registry,
    compute_store: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore] = compute_job_store,
    async_result_store_: AsyncResultStore | RuntimeStoreProxy[AsyncResultStore] = async_result_store,
    lineage_store: LineageMetadataStore | RuntimeStoreProxy[LineageMetadataStore] = lineage_metadata_store,
) -> None:
    execution_store.create_schema()
    compute_store.create_schema()
    async_result_store_.create_schema()
    lineage_store.create_schema()
