from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.composites import CompositeDefinition, CompositeMemberReturnFact
from app.services.composite_metadata_store import composite_metadata_store
from main import app


def _seed_definition() -> None:
    composite_metadata_store.upsert_definition(
        CompositeDefinition.model_validate(
            {
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "display_name": "Private Banking Global Balanced USD Composite",
                "strategy_code": "GLOBAL_BALANCED",
                "reporting_currency": "USD",
                "inception_date": "2026-01-01",
                "source_authority": {
                    "definition_owner": "lotus-manage",
                    "membership_owner": "lotus-manage",
                    "member_return_owner": "lotus-performance",
                    "asset_owner": "lotus-core",
                    "benchmark_owner": "lotus-core",
                    "policy_version": "composite-source-authority.v1",
                },
            }
        )
    )


def _seed_fact(
    portfolio_id: str,
    return_value: str,
    beginning_market_value: str,
    *,
    status: str = "READY",
    reason_codes: list[str] | None = None,
) -> None:
    composite_metadata_store.upsert_member_return_fact(
        CompositeMemberReturnFact.model_validate(
            {
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "portfolio_id": portfolio_id,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "return_value": return_value,
                "beginning_market_value": beginning_market_value,
                "ending_market_value": "1012500.00",
                "reporting_currency": "USD",
                "calculation_id": f"calc-{portfolio_id}",
                "source_snapshot_id": f"snapshot-{portfolio_id}",
                "source_fingerprint": f"sha256:{portfolio_id}",
                "status": status,
                "reason_codes": reason_codes or [],
            }
        )
    )


def test_composite_twr_api_calculates_from_persisted_member_facts():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        _seed_fact("P1", "0.0100", "100.00")
        _seed_fact("P2", "0.0300", "300.00")

        response = client.post(
            "/performance/composites/twr",
            json={
                "calculation_id": "7f2b08b0-58e5-49be-b3ef-7a9cfb0321ce",
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["cumulative_return"] == "0.025000000000"
    assert payload["periods"][0]["member_count"] == 2
    assert payload["periods"][0]["return_view"] == "NET_ACTUAL"
    assert payload["periods"][0]["reporting_currency"] == "USD"
    assert payload["periods"][0]["source_fingerprints"] == ["sha256:P1", "sha256:P2"]
    assert payload["periods"][0]["restatement_versions"] == ["v1"]
    assert payload["periods"][0]["member_contributions"][1]["beginning_asset_weight"] == "0.750000000000"
    assert payload["periods"][0]["member_contributions"][1]["source_fingerprint"] == "sha256:P2"
    assert payload["methodology"] == "persisted_member_return_asset_weighted_twr_v1"


def test_composite_twr_api_returns_not_found_for_unknown_definition():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()

        response = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "MISSING_COMPOSITE",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "COMPOSITE_NOT_FOUND"


def test_composite_twr_api_returns_unprocessable_for_empty_persisted_fact_window():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()

        response = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "NO_MEMBER_RETURN_FACTS"


def test_composite_twr_api_returns_degraded_reason_codes_for_non_ready_member_facts():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        _seed_fact("P1", "0.0100", "100.00")
        _seed_fact("P2", "0.0300", "300.00", status="DEGRADED", reason_codes=["missing_final_valuation"])

        response = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DEGRADED"
    assert payload["reason_codes"] == ["missing_final_valuation"]
    assert payload["periods"][0]["excluded_member_count"] == 1
    assert payload["periods"][0]["reason_codes"] == ["missing_final_valuation"]


def test_composite_twr_api_rejects_invalid_window_before_calculation():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()

        response = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-02-01",
                "period_end": "2026-01-31",
            },
        )

    assert response.status_code == 422
    assert "period_end cannot be before period_start" in response.text


def test_composite_inspection_api_returns_artifacts_from_persisted_facts():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        _seed_fact("P1", "0.0100", "100.00")
        _seed_fact("P2", "0.0300", "300.00")

        response = client.post(
            "/performance/composites/inspect",
            json={
                "inspection_id": "8d1e37d2-aeca-488c-bd43-77dbf6739103",
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    artifacts = {artifact["artifact_name"]: artifact for artifact in payload["artifacts"]}
    assert payload["verdict"] == "supportable"
    assert artifacts["member_inputs.csv"]["access_classification"] == "operator_only"
    assert artifacts["composite_returns.csv"]["access_classification"] == "customer_consumable"
    assert "PB_GLOBAL_BALANCED_USD" in artifacts["support_brief.md"]["artifact_content"]
