import logging
from typing import Any

from app.enterprise_audit_events import (
    _ENTERPRISE_AUDIT_EVENT_NAME,
    _ENTERPRISE_AUDIT_EXTRA_KEY,
    _audit_event_payload,
)


def emit_audit_event(
    *,
    logger: logging.Logger,
    action: str,
    actor_id: str,
    tenant_id: str,
    role: str,
    correlation_id: str | None,
    metadata: dict[str, Any],
) -> None:
    logger.info(
        _ENTERPRISE_AUDIT_EVENT_NAME,
        extra={
            _ENTERPRISE_AUDIT_EXTRA_KEY: _audit_event_payload(
                action=action,
                actor_id=actor_id,
                tenant_id=tenant_id,
                role=role,
                correlation_id=correlation_id,
                metadata=metadata,
            )
        },
    )
