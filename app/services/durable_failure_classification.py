from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from core.errors import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_408_REQUEST_TIMEOUT,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_502_BAD_GATEWAY,
    HTTP_503_SERVICE_UNAVAILABLE,
    HTTP_504_GATEWAY_TIMEOUT,
    APIError,
)

logger = logging.getLogger(__name__)

DURABLE_FAILURE_CONTRACT_VERSION = "v1"
GENERIC_ASYNC_FAILURE_CODE = "ASYNC_EXECUTION_FAILED"
GENERIC_ASYNC_FAILURE_MESSAGE = "Compute job execution failed unexpectedly. Use the correlation_id for support."
_MAX_CODE_LENGTH = 128
_MAX_MESSAGE_LENGTH = 512
_MAX_REMEDIATION_LENGTH = 512
_ERROR_CODE_BY_STATUS = {
    HTTP_400_BAD_REQUEST: "INVALID_REQUEST",
    HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    HTTP_403_FORBIDDEN: "FORBIDDEN",
    HTTP_404_NOT_FOUND: "RESOURCE_NOT_FOUND",
    HTTP_409_CONFLICT: "CONFLICT",
    HTTP_422_UNPROCESSABLE: "INVALID_REQUEST",
    HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
    HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_SERVER_ERROR",
    HTTP_502_BAD_GATEWAY: "SOURCE_UNAVAILABLE",
    HTTP_503_SERVICE_UNAVAILABLE: "SOURCE_UNAVAILABLE",
    HTTP_504_GATEWAY_TIMEOUT: "SOURCE_UNAVAILABLE",
}
_RETRYABLE_STATUSES = frozenset(
    {
        HTTP_408_REQUEST_TIMEOUT,
        HTTP_429_TOO_MANY_REQUESTS,
        HTTP_500_INTERNAL_SERVER_ERROR,
        HTTP_502_BAD_GATEWAY,
        HTTP_503_SERVICE_UNAVAILABLE,
        HTTP_504_GATEWAY_TIMEOUT,
    }
)
_REPLAYABLE_STATUS_CODES = frozenset(_ERROR_CODE_BY_STATUS) | {HTTP_408_REQUEST_TIMEOUT}


@dataclass(frozen=True)
class DurableFailureClassification:
    contract_version: str
    status_code: int
    error_code: str
    message: str
    retryable: bool
    remediation_hint: str | None = None

    def to_json(self) -> str:
        payload: dict[str, str | int | bool] = {
            "contract_version": self.contract_version,
            "status_code": self.status_code,
            "error_code": self.error_code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.remediation_hint is not None:
            payload["remediation_hint"] = self.remediation_hint
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def to_api_error(self) -> APIError:
        return APIError(
            status_code=self.status_code,
            detail=self.message,
            error_code=self.error_code,
            retryable=self.retryable,
            remediation_hint=self.remediation_hint,
        )


def classify_durable_failure(
    exc: Exception,
    *,
    retryable: bool | None = None,
) -> DurableFailureClassification:
    if not isinstance(exc, APIError):
        return generic_durable_failure(retryable=bool(retryable))
    status_code = int(exc.status_code)
    if status_code not in _REPLAYABLE_STATUS_CODES:
        return generic_durable_failure(retryable=bool(retryable))
    message = _safe_api_error_message(exc)
    return DurableFailureClassification(
        contract_version=DURABLE_FAILURE_CONTRACT_VERSION,
        status_code=status_code,
        error_code=_bounded_text(_resolved_error_code(exc), _MAX_CODE_LENGTH),
        message=_bounded_text(message, _MAX_MESSAGE_LENGTH),
        retryable=_resolved_retryable(exc) if retryable is None else retryable,
        remediation_hint=_optional_bounded_text(
            exc.remediation_hint or _detail_value(exc, "remediation_hint"),
            _MAX_REMEDIATION_LENGTH,
        ),
    )


def generic_durable_failure(*, retryable: bool = False) -> DurableFailureClassification:
    return DurableFailureClassification(
        contract_version=DURABLE_FAILURE_CONTRACT_VERSION,
        status_code=HTTP_409_CONFLICT,
        error_code=GENERIC_ASYNC_FAILURE_CODE,
        message=GENERIC_ASYNC_FAILURE_MESSAGE,
        retryable=retryable,
    )


def load_durable_failure(raw_value: str | None, *, identity: str) -> DurableFailureClassification | None:
    if raw_value is None:
        return None
    try:
        payload = json.loads(raw_value)
        if not isinstance(payload, dict):
            raise ValueError("failure classification must be an object")
        _validate_payload_types(payload)
        classification = DurableFailureClassification(
            contract_version=payload["contract_version"],
            status_code=payload["status_code"],
            error_code=payload["error_code"],
            message=payload["message"],
            retryable=payload["retryable"],
            remediation_hint=_optional_bounded_text(payload.get("remediation_hint"), _MAX_REMEDIATION_LENGTH),
        )
        _validate_classification(classification)
        return classification
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning(
            "Stored durable failure classification is invalid; using legacy generic handling.",
            extra={"identity": identity, "failure_classification": "invalid_durable_failure_classification"},
        )
        return None


def _validate_payload_types(payload: dict[str, Any]) -> None:
    required_types = {
        "contract_version": str,
        "status_code": int,
        "error_code": str,
        "message": str,
        "retryable": bool,
    }
    for field_name, expected_type in required_types.items():
        if type(payload.get(field_name)) is not expected_type:
            raise ValueError(f"invalid durable failure {field_name} type")
    remediation_hint = payload.get("remediation_hint")
    if remediation_hint is not None and type(remediation_hint) is not str:
        raise ValueError("invalid durable failure remediation type")


def _safe_api_error_message(exc: APIError) -> str:
    if exc.status_code >= HTTP_500_INTERNAL_SERVER_ERROR:
        return GENERIC_ASYNC_FAILURE_MESSAGE
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return "The asynchronous calculation was refused."


def _resolved_error_code(exc: APIError) -> str:
    return (
        _nonblank_string(exc.error_code)
        or _nonblank_string(_detail_value(exc, "error_code"))
        or _nonblank_string(_detail_value(exc, "code"))
        or _ERROR_CODE_BY_STATUS.get(exc.status_code, "INTERNAL_SERVER_ERROR")
    )


def _resolved_retryable(exc: APIError) -> bool:
    if exc.retryable is not None:
        return exc.retryable
    detail_retryable = _detail_value(exc, "retryable")
    if isinstance(detail_retryable, bool):
        return detail_retryable
    return exc.status_code in _RETRYABLE_STATUSES


def _detail_value(exc: APIError, key: str) -> Any:
    return exc.detail.get(key) if isinstance(exc.detail, dict) else getattr(exc, key, None)


def _nonblank_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _validate_classification(classification: DurableFailureClassification) -> None:
    if classification.contract_version != DURABLE_FAILURE_CONTRACT_VERSION:
        raise ValueError("unsupported durable failure contract version")
    if classification.status_code not in _REPLAYABLE_STATUS_CODES:
        raise ValueError("invalid durable failure status")
    if not isinstance(classification.retryable, bool):
        raise ValueError("invalid durable failure retryability")
    if not classification.error_code or len(classification.error_code) > _MAX_CODE_LENGTH:
        raise ValueError("invalid durable failure code")
    if not classification.message or len(classification.message) > _MAX_MESSAGE_LENGTH:
        raise ValueError("invalid durable failure message")


def _bounded_text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit]


def _optional_bounded_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]
