from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.application_responses import ApplicationHttpResponse
from app.enterprise_authorization import _missing_headers_reason
from app.enterprise_capability_rules import _CAPABILITY_OPERATIONS_RUNTIME_READ
from app.enterprise_request_context import (
    _has_service_identity,
    _header_capabilities,
    _missing_required_headers,
    _normalized_headers,
)
from app.enterprise_response_envelopes import _authorization_denied_application_response
from app.enterprise_runtime_config import _privileged_read_authz_enabled
from app.services.execution_registry import ExecutionRecord

_PORTFOLIO_ID_HEADER = "x-portfolio-id"
_TENANT_ID_HEADER = "x-tenant-id"
_RESULT_ACCESS_DENIED_REASON = "missing_result_access:operations.runtime.read_or_matching_portfolio_id"
_RESULT_TENANT_ACCESS_DENIED_REASON = "result_tenant_authority_mismatch"
_RESULT_TENANT_AUTHORITY_UNAVAILABLE_REASON = "result_tenant_authority_unavailable"


def authorize_calculation_result_access(
    *,
    execution: ExecutionRecord,
    headers: Mapping[str, Any] | None,
) -> ApplicationHttpResponse | None:
    normalized_headers = _normalized_headers(headers or {})
    if _privileged_read_authz_enabled():
        denial_reason = _calculation_result_access_denial_reason(
            execution=execution,
            normalized_headers=normalized_headers,
        )
    else:
        denial_reason = _tenant_access_denial_reason(
            execution=execution,
            normalized_headers=normalized_headers,
        )
    if denial_reason is None:
        return None
    return _authorization_denied_application_response(denial_reason)


def _calculation_result_access_denial_reason(
    *,
    execution: ExecutionRecord,
    normalized_headers: Mapping[str, str],
) -> str | None:
    missing_headers = _missing_required_headers(normalized_headers)
    if missing_headers:
        return _missing_headers_reason(missing_headers)
    if not _has_service_identity(normalized_headers):
        return "missing_service_identity"
    tenant_denial = _tenant_access_denial_reason(
        execution=execution,
        normalized_headers=normalized_headers,
    )
    if tenant_denial is not None:
        return tenant_denial
    if _has_calculation_result_access(
        execution=execution,
        normalized_headers=normalized_headers,
    ):
        return None
    return _RESULT_ACCESS_DENIED_REASON


def _tenant_access_denial_reason(
    *,
    execution: ExecutionRecord,
    normalized_headers: Mapping[str, str],
) -> str | None:
    if execution.tenant_id is None:
        return _RESULT_TENANT_AUTHORITY_UNAVAILABLE_REASON
    if not execution.tenant_id:
        return None
    if normalized_headers.get(_TENANT_ID_HEADER) != execution.tenant_id:
        return _RESULT_TENANT_ACCESS_DENIED_REASON
    return None


def _has_calculation_result_access(
    *,
    execution: ExecutionRecord,
    normalized_headers: Mapping[str, str],
) -> bool:
    return _has_privileged_result_read(normalized_headers) or _has_matching_portfolio_entitlement(
        execution=execution,
        normalized_headers=normalized_headers,
    )


def _has_privileged_result_read(normalized_headers: Mapping[str, str]) -> bool:
    return _CAPABILITY_OPERATIONS_RUNTIME_READ in _header_capabilities(normalized_headers)


def _has_matching_portfolio_entitlement(
    *,
    execution: ExecutionRecord,
    normalized_headers: Mapping[str, str],
) -> bool:
    portfolio_id = (execution.portfolio_id or "").strip()
    requested_portfolio_id = normalized_headers.get(_PORTFOLIO_ID_HEADER, "")
    return bool(portfolio_id and requested_portfolio_id and requested_portfolio_id == portfolio_id)
