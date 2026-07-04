from uuid import uuid4

from app.enterprise_response_envelopes import (
    _AUTHORIZATION_POLICY_DENIED_DETAIL,
    _RESPONSE_DETAIL_KEY,
    _RESPONSE_REASON_KEY,
)
from app.enterprise_runtime_config import _ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ
from app.services.calculation_result_access import (
    _RESULT_ACCESS_DENIED_REASON,
    authorize_calculation_result_access,
)
from app.services.execution_registry import ExecutionRecord, ExecutionStatus


def _execution_record(*, portfolio_id: str | None = "PORT-1") -> ExecutionRecord:
    return ExecutionRecord(
        calculation_id=uuid4(),
        analytics_type="TWR",
        portfolio_id=portfolio_id,
        execution_mode="async",
        status=ExecutionStatus.COMPLETE,
        requested_window={},
        input_fingerprint=None,
        calculation_hash=None,
        error_message=None,
        created_at_utc="2026-06-30T00:00:00Z",
        started_at_utc=None,
        completed_at_utc=None,
        stages=[],
        upstream_snapshots=[],
    )


def _identity_headers(**extra_headers: str) -> dict[str, str]:
    return {
        "X-Actor-Id": "advisor-1",
        "X-Tenant-Id": "tenant-private-bank",
        "X-Role": "advisor",
        "X-Correlation-Id": "corr-1",
        "X-Service-Identity": "lotus-gateway",
        **extra_headers,
    }


def _response_body(response) -> dict[str, str | None]:
    return response.content


def test_calculation_result_access_is_relaxed_when_privileged_read_authz_disabled(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "false")

    assert authorize_calculation_result_access(execution=_execution_record(), headers={}) is None


def test_calculation_result_access_requires_enterprise_identity_headers(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")

    response = authorize_calculation_result_access(execution=_execution_record(), headers={})

    assert response is not None
    assert response.status_code == 403
    assert _response_body(response)[_RESPONSE_DETAIL_KEY] == _AUTHORIZATION_POLICY_DENIED_DETAIL
    assert _response_body(response)[_RESPONSE_REASON_KEY].startswith("missing_headers:")


def test_calculation_result_access_requires_service_identity(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")

    response = authorize_calculation_result_access(
        execution=_execution_record(),
        headers={
            "X-Actor-Id": "advisor-1",
            "X-Tenant-Id": "tenant-private-bank",
            "X-Role": "advisor",
            "X-Correlation-Id": "corr-1",
        },
    )

    assert response is not None
    assert response.status_code == 403
    assert _response_body(response) == {
        _RESPONSE_DETAIL_KEY: _AUTHORIZATION_POLICY_DENIED_DETAIL,
        _RESPONSE_REASON_KEY: "missing_service_identity",
    }


def test_calculation_result_access_allows_matching_portfolio_entitlement(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")

    response = authorize_calculation_result_access(
        execution=_execution_record(portfolio_id="PORT-1"),
        headers=_identity_headers(**{"X-Portfolio-Id": "PORT-1"}),
    )

    assert response is None


def test_calculation_result_access_allows_runtime_read_capability(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")

    response = authorize_calculation_result_access(
        execution=_execution_record(portfolio_id="PORT-1"),
        headers=_identity_headers(**{"X-Capabilities": "operations.runtime.read"}),
    )

    assert response is None


def test_calculation_result_access_denies_different_portfolio_without_privileged_read(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")

    response = authorize_calculation_result_access(
        execution=_execution_record(portfolio_id="PORT-1"),
        headers=_identity_headers(**{"X-Portfolio-Id": "PORT-2"}),
    )

    assert response is not None
    assert response.status_code == 403
    assert _response_body(response) == {
        _RESPONSE_DETAIL_KEY: _AUTHORIZATION_POLICY_DENIED_DETAIL,
        _RESPONSE_REASON_KEY: _RESULT_ACCESS_DENIED_REASON,
    }
