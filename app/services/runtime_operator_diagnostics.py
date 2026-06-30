from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Literal

RuntimeOperatorReadSource = Literal["compute", "lineage"]
RuntimeOperatorReadOperation = Literal["recovery", "work_item"]

COMPUTE_RECOVERY_READ_FAILED = "compute_recovery_read_failed"
LINEAGE_RECOVERY_READ_FAILED = "lineage_recovery_read_failed"
COMPUTE_WORK_ITEM_READ_FAILED = "compute_work_item_read_failed"
LINEAGE_WORK_ITEM_READ_FAILED = "lineage_work_item_read_failed"

_READ_FAILURE_REASONS: dict[tuple[RuntimeOperatorReadSource, RuntimeOperatorReadOperation], str] = {
    ("compute", "recovery"): COMPUTE_RECOVERY_READ_FAILED,
    ("lineage", "recovery"): LINEAGE_RECOVERY_READ_FAILED,
    ("compute", "work_item"): COMPUTE_WORK_ITEM_READ_FAILED,
    ("lineage", "work_item"): LINEAGE_WORK_ITEM_READ_FAILED,
}


def runtime_operator_read_failed_reason(
    *,
    source: RuntimeOperatorReadSource,
    operation: RuntimeOperatorReadOperation,
) -> str:
    return _READ_FAILURE_REASONS[(source, operation)]


def log_runtime_operator_read_failure(
    *,
    logger: logging.Logger,
    source: RuntimeOperatorReadSource,
    operation: RuntimeOperatorReadOperation,
    exception: Exception,
    safe_filters: Mapping[str, object],
) -> str:
    reason = runtime_operator_read_failed_reason(source=source, operation=operation)
    logger.warning(
        "Runtime operator read degraded.",
        exc_info=True,
        extra={
            "extra_fields": {
                "event_name": "runtime_operator_read_degraded",
                "source": source,
                "operation": operation,
                "reason": reason,
                "exception_class": type(exception).__name__,
                **dict(safe_filters),
            }
        },
    )
    return reason
