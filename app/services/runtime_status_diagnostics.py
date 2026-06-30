from __future__ import annotations

import logging

COMPUTE_QUEUE_STATUS_READ_FAILED = "compute_queue_status_read_failed"
LINEAGE_QUEUE_STATUS_READ_FAILED = "lineage_queue_status_read_failed"
RECOVERY_DRILL_HISTORY_READ_FAILED = "recovery_drill_history_read_failed"
RUNTIME_RETENTION_HISTORY_READ_FAILED = "runtime_retention_history_read_failed"
RUNTIME_RETENTION_PREVIEW_READ_FAILED = "runtime_retention_preview_read_failed"
RECOVERY_DRILL_OPERATOR_ACTION_READ_FAILED = "recovery_drill_operator_action_read_failed"
RUNTIME_RETENTION_OPERATOR_ACTION_READ_FAILED = "runtime_retention_operator_action_read_failed"

_OPERATOR_ACTION_READ_FAILURE_REASONS = {
    "recovery_drill": RECOVERY_DRILL_OPERATOR_ACTION_READ_FAILED,
    "runtime_retention_cleanup": RUNTIME_RETENTION_OPERATOR_ACTION_READ_FAILED,
}


def operator_action_read_failed_reason(action_name: str) -> str:
    return _OPERATOR_ACTION_READ_FAILURE_REASONS.get(action_name, f"{action_name}_operator_action_read_failed")


def log_runtime_status_read_failure(
    *,
    logger: logging.Logger,
    component: str,
    operation: str,
    reason: str,
    exception: Exception,
) -> str:
    logger.warning(
        "Runtime status read degraded.",
        exc_info=True,
        extra={
            "extra_fields": {
                "event_name": "runtime_status_read_degraded",
                "component": component,
                "operation": operation,
                "reason": reason,
                "exception_class": type(exception).__name__,
            }
        },
    )
    return reason
