from __future__ import annotations

from app.adapters.execution_polling_store import execution_polling_store
from app.ports.execution_polling import ExecutionPollingStore


def get_execution_polling_store() -> ExecutionPollingStore:
    return execution_polling_store
