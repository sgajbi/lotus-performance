from uuid import uuid4

import pytest

from app.models.inspection_requests import TWRInspectionRequest, TWRInspectionSubjectType
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR
from app.services.inspection.subject_resolution import resolve_twr_inspection_subject


def test_resolve_twr_inspection_subject_accepts_twr_execution(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setattr(
        "app.services.inspection.subject_resolution.execution_registry.get_execution_for_tenant",
        lambda _calculation_id, *, tenant_id: type(
            "Execution",
            (),
            {"analytics_type": ANALYTICS_WORKFLOW_TWR, "portfolio_id": "P1"},
        )(),
    )

    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(calculation_id),
        }
    )

    resolved = resolve_twr_inspection_subject(request)

    assert resolved.subject_calculation_id == calculation_id
    assert resolved.portfolio_id == "P1"


def test_resolve_twr_inspection_subject_rejects_non_twr_execution(monkeypatch):
    calculation_id = uuid4()
    monkeypatch.setattr(
        "app.services.inspection.subject_resolution.execution_registry.get_execution_for_tenant",
        lambda _calculation_id, *, tenant_id: type(
            "Execution",
            (),
            {"analytics_type": "MWR", "portfolio_id": "P1"},
        )(),
    )

    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(calculation_id),
        }
    )

    with pytest.raises(ValueError, match="Inspection subject must reference a TWR calculation"):
        resolve_twr_inspection_subject(request)


def test_resolve_twr_inspection_subject_requires_request_payload_for_twr_request():
    request = TWRInspectionRequest.model_construct(
        subject_type=TWRInspectionSubjectType.TWR_REQUEST,
        request=None,
        subject_calculation_id=None,
    )

    with pytest.raises(ValueError, match="twr_request inspection requires request payload"):
        resolve_twr_inspection_subject(request)


def test_resolve_twr_inspection_subject_preserves_tenantless_stateless_authority(monkeypatch):
    calculation_id = uuid4()
    tenantless_execution = type(
        "Execution",
        (),
        {"analytics_type": ANALYTICS_WORKFLOW_TWR, "portfolio_id": "P1", "tenant_id": ""},
    )()
    monkeypatch.setattr(
        "app.services.inspection.subject_resolution.execution_registry.get_execution_for_tenant",
        lambda _calculation_id, *, tenant_id: None,
    )
    monkeypatch.setattr(
        "app.services.inspection.subject_resolution.execution_registry.get_execution",
        lambda _calculation_id: tenantless_execution,
    )
    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(calculation_id),
        }
    )

    resolved = resolve_twr_inspection_subject(request)

    assert resolved.related_execution is tenantless_execution


def test_resolve_twr_inspection_subject_does_not_fallback_to_another_tenant(monkeypatch):
    calculation_id = uuid4()
    other_tenant_execution = type(
        "Execution",
        (),
        {"analytics_type": ANALYTICS_WORKFLOW_TWR, "portfolio_id": "P1", "tenant_id": "tenant-b"},
    )()
    monkeypatch.setattr(
        "app.services.inspection.subject_resolution.execution_registry.get_execution_for_tenant",
        lambda _calculation_id, *, tenant_id: None,
    )
    monkeypatch.setattr(
        "app.services.inspection.subject_resolution.execution_registry.get_execution",
        lambda _calculation_id: other_tenant_execution,
    )
    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(calculation_id),
        }
    )

    with pytest.raises(KeyError, match="TWR calculation execution not found"):
        resolve_twr_inspection_subject(request)
