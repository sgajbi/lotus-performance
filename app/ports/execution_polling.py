from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.services.async_result_store import AsyncResultRecord
from app.services.compute_job_store import ComputeJobRecord
from app.services.execution_registry import ExecutionRecord, ExecutionStageRecord, UpstreamSnapshotRecord

ExecutionPollingAsyncResultRecord = AsyncResultRecord
ExecutionPollingComputeJobRecord = ComputeJobRecord
ExecutionPollingExecutionRecord = ExecutionRecord
ExecutionPollingStageRecord = ExecutionStageRecord
ExecutionPollingUpstreamSnapshotRecord = UpstreamSnapshotRecord


class ExecutionPollingStore(Protocol):
    """Port used by execution polling use cases to read durable runtime state."""

    def get_execution(self, calculation_id: UUID) -> ExecutionRecord | None: ...

    def get_job(self, calculation_id: UUID) -> ComputeJobRecord | None: ...

    def get_result(self, calculation_id: UUID) -> AsyncResultRecord | None: ...
