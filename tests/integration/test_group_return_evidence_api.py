from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from app.models.group_return_evidence import GroupReturnEvidenceResponse
from main import app


def _response() -> GroupReturnEvidenceResponse:
    return GroupReturnEvidenceResponse.model_validate(
        {
            "calculation_id": "00000000-0000-0000-0000-000000000571",
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "benchmark_id": "BMK_PB_GLOBAL_BALANCED",
            "as_of_date": "2026-04-10",
            "window": {"start_date": "2026-04-01", "end_date": "2026-04-02"},
            "grouping_dimension": "SECTOR",
            "reporting_currency": "USD",
            "return_basis": "SOURCE_POSITION_AND_BENCHMARK_COMPONENT_GROSS_TWR",
            "valuation_basis": "SOURCE_REPORTED_BEGINNING_AND_ENDING_MARKET_VALUES",
            "weight_basis": "SIGNED_BEGINNING_CAPITAL_AND_BENCHMARK_BOP_WEIGHT",
            "coverage": {
                "status": "COMPLETE",
                "reason_codes": [],
                "observed_dates": ["2026-04-01"],
                "reconciliation_tolerance": "0.000001",
            },
            "aggregate_returns": [
                {
                    "date": "2026-04-01",
                    "portfolio_return": Decimal("0.014"),
                    "weighted_portfolio_return": Decimal("0.014"),
                    "portfolio_reconciliation_delta": Decimal("0"),
                    "benchmark_return": Decimal("0.006"),
                    "active_return": Decimal("0.008"),
                    "group_active_contribution_delta": Decimal("0"),
                }
            ],
            "rows": [
                {
                    "date": "2026-04-01",
                    "group_id": "SECTOR:equity",
                    "group_label": "Equity",
                    "portfolio_group_return": Decimal("0.02"),
                    "benchmark_group_return": Decimal("0.01"),
                    "portfolio_weight": Decimal("0.6"),
                    "benchmark_weight": Decimal("0.5"),
                    "active_contribution": Decimal("0.007"),
                },
                {
                    "date": "2026-04-01",
                    "group_id": "SECTOR:fixed_income",
                    "group_label": "Fixed Income",
                    "portfolio_group_return": Decimal("0.005"),
                    "benchmark_group_return": Decimal("0.002"),
                    "portfolio_weight": Decimal("0.4"),
                    "benchmark_weight": Decimal("0.5"),
                    "active_contribution": Decimal("0.001"),
                },
            ],
            "source_lineage": {
                "execution_id": "00000000-0000-0000-0000-000000000571",
                "tenant_scope": "ADMITTED_TENANT",
                "source_cut_id": "sha256:group-return-evidence-cut",
                "upstream_revision_status": "NOT_PROVIDED_BY_SOURCE",
                "snapshots": [],
            },
        }
    )


def test_group_return_evidence_api_publishes_the_versioned_producer_contract(monkeypatch) -> None:
    expected = _response()

    async def _calculate(request):
        assert request.calculation_id == UUID("00000000-0000-0000-0000-000000000571")
        assert request.grouping_dimension.value == "SECTOR"
        assert request.reporting_currency == "USD"
        return expected

    monkeypatch.setattr("app.api.endpoints.group_return_evidence.calculate_group_return_evidence_response", _calculate)
    payload = {
        "calculation_id": "00000000-0000-0000-0000-000000000571",
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "benchmark_id": "BMK_PB_GLOBAL_BALANCED",
        "as_of_date": "2026-04-10",
        "window": {"start_date": "2026-04-01", "end_date": "2026-04-02"},
        "grouping_dimension": "SECTOR",
        "reporting_currency": "USD",
    }

    with TestClient(app) as client:
        response = client.post("/integration/attribution/group-return-evidence/v1", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "v1"
    assert body["coverage"]["status"] == "COMPLETE"
    assert body["aggregate_returns"][0]["active_return"] == "0.008"
    assert sum(Decimal(row["active_contribution"]) for row in body["rows"]) == Decimal("0.008")
    assert body["source_lineage"]["tenant_scope"] == "ADMITTED_TENANT"


def test_group_return_evidence_api_rejects_non_uppercase_currency() -> None:
    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-04-10",
        "window": {"start_date": "2026-04-01", "end_date": "2026-04-02"},
        "grouping_dimension": "SECTOR",
        "reporting_currency": "usd",
    }

    with TestClient(app) as client:
        response = client.post("/integration/attribution/group-return-evidence/v1", json=payload)

    assert response.status_code == 422
    assert "reporting_currency" in str(response.json())


def test_group_return_evidence_api_rejects_an_inverted_inclusive_business_date_window() -> None:
    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-04-10",
        "window": {"start_date": "2026-04-02", "end_date": "2026-04-01"},
        "grouping_dimension": "SECTOR",
        "reporting_currency": "USD",
    }

    with TestClient(app) as client:
        response = client.post("/integration/attribution/group-return-evidence/v1", json=payload)

    assert response.status_code == 422
    assert "window.start_date" in str(response.json())
