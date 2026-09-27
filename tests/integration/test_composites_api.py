from __future__ import annotations

from decimal import Decimal

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
                "reporting_currency": "usd",
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
    return_view: str = "NET_ACTUAL",
    reporting_currency: str = "USD",
    restatement_version: str = "v1",
    restatement_sequence: int = 1,
) -> CompositeMemberReturnFact:
    ending_market_value = Decimal(beginning_market_value) * (Decimal("1") + Decimal(return_value))
    fact = CompositeMemberReturnFact.model_validate(
        {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "portfolio_id": portfolio_id,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "return_value": return_value,
            "return_view": return_view,
            "beginning_market_value": beginning_market_value,
            "ending_market_value": str(ending_market_value),
            "reporting_currency": reporting_currency,
            "calculation_id": f"calc-{portfolio_id}-{return_view}-{restatement_sequence}",
            "source_snapshot_id": f"snapshot-{portfolio_id}-{return_view}-{restatement_sequence}",
            "source_fingerprint": f"sha256:{portfolio_id}-{return_view}-{restatement_sequence}",
            "restatement_version": restatement_version,
            "restatement_sequence": restatement_sequence,
            "status": status,
            "reason_codes": reason_codes or [],
        }
    )
    composite_metadata_store.upsert_member_return_fact(fact)
    return fact


def _complete_publication(*facts: CompositeMemberReturnFact) -> None:
    first = facts[0]
    composite_metadata_store.complete_member_return_fact_publication(
        composite_id=first.composite_id,
        return_view=first.return_view,
        reporting_currency=first.reporting_currency,
        restatement_sequence=first.restatement_sequence,
        period_start=first.period_start,
        period_end=first.period_end,
        expected_families={(fact.portfolio_id, fact.period_start, fact.period_end) for fact in facts},
        source_fingerprint=(
            f"sha256:api-publication-{first.return_view.value}-{first.reporting_currency}-{first.restatement_sequence}"
        ),
    )


def test_composite_twr_api_calculates_from_persisted_member_facts():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        facts = (_seed_fact("P1", "0.0100", "100.00"), _seed_fact("P2", "0.0300", "300.00"))
        _complete_publication(*facts)

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
    assert payload["periods"][0]["source_fingerprints"] == [
        "sha256:P1-NET_ACTUAL-1",
        "sha256:P2-NET_ACTUAL-1",
    ]
    assert payload["periods"][0]["restatement_versions"] == ["v1"]
    assert payload["periods"][0]["restatement_sequence"] == 1
    assert payload["periods"][0]["member_contributions"][1]["beginning_asset_weight"] == "0.750000000000"
    assert payload["periods"][0]["member_contributions"][1]["source_fingerprint"] == "sha256:P2-NET_ACTUAL-1"
    assert payload["methodology"] == "persisted_member_return_asset_weighted_twr_v1"


def test_composite_twr_api_selects_immutable_net_versions_and_gross_view():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        _seed_fact("P1", "0.0100", "100.00", restatement_version="published", restatement_sequence=1)
        latest_net_fact = _seed_fact("P1", "0.0200", "100.00", restatement_version="correction", restatement_sequence=2)
        gross_fact = _seed_fact(
            "P1",
            "0.0300",
            "100.00",
            return_view="GROSS",
            restatement_version="published",
            restatement_sequence=1,
        )
        _complete_publication(latest_net_fact)
        _complete_publication(gross_fact)

        latest_net = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "return_view": "NET_ACTUAL",
                "reporting_currency": "usd",
            },
        )
        original_net = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "return_view": "NET_ACTUAL",
                "reporting_currency": "USD",
                "restatement_sequence": 1,
            },
        )
        gross = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "return_view": "GROSS",
                "reporting_currency": "USD",
            },
        )

    assert latest_net.status_code == 200
    assert original_net.status_code == 200
    assert gross.status_code == 200
    assert latest_net.json()["cumulative_return"] == "0.020000000000"
    assert original_net.json()["cumulative_return"] == "0.010000000000"
    assert gross.json()["cumulative_return"] == "0.030000000000"
    expected_figures = (
        (latest_net.json(), "0.020000000000", "102.000000", "NET_ACTUAL", 2),
        (original_net.json(), "0.010000000000", "101.000000", "NET_ACTUAL", 1),
        (gross.json(), "0.030000000000", "103.000000", "GROSS", 1),
    )
    for payload, expected_return, expected_ending_assets, expected_view, expected_sequence in expected_figures:
        period = payload["periods"][0]
        contribution = period["member_contributions"][0]
        assert period["return_value"] == expected_return
        assert period["cumulative_return"] == expected_return
        assert period["beginning_market_value"] == "100.000000"
        assert period["ending_market_value"] == expected_ending_assets
        assert period["member_count"] == 1
        assert period["excluded_member_count"] == 0
        assert period["dispersion_equal_weight"] is None
        assert period["return_view"] == expected_view
        assert period["reporting_currency"] == "USD"
        assert contribution["return_value"] == expected_return
        assert contribution["beginning_asset_weight"] == "1.000000000000"
        assert contribution["contribution"] == expected_return
        assert contribution["restatement_sequence"] == expected_sequence


def test_composite_twr_api_replays_pinned_set_before_later_member_was_added():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        _seed_fact("P1", "0.0100", "100.00", restatement_version="published", restatement_sequence=1)
        latest_facts = (
            _seed_fact("P1", "0.0200", "100.00", restatement_version="correction", restatement_sequence=2),
            _seed_fact("P2", "0.0300", "300.00", restatement_version="added-member", restatement_sequence=2),
        )
        _complete_publication(*latest_facts)

        pinned = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "restatement_sequence": 1,
            },
        )
        latest = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

    assert pinned.status_code == 200
    assert pinned.json()["cumulative_return"] == "0.010000000000"
    assert pinned.json()["periods"][0]["member_count"] == 1
    assert latest.status_code == 200
    assert latest.json()["cumulative_return"] == "0.027500000000"


def test_composite_twr_api_refuses_partial_latest_fact_sequence():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        _seed_fact("P1", "0.0100", "100.00", restatement_version="published", restatement_sequence=1)
        _seed_fact("P2", "0.0300", "300.00", restatement_version="published", restatement_sequence=1)
        _seed_fact("P1", "0.0200", "100.00", restatement_version="correction", restatement_sequence=2)

        response = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": "PB_GLOBAL_BALANCED_USD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "COMPOSITE_FACT_SELECTION_INCOMPLETE"


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


def test_composite_apis_reject_explicit_sequence_when_fact_universe_is_empty():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        common_request = {
            "composite_id": "PB_GLOBAL_BALANCED_USD",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "restatement_sequence": 7,
        }

        twr_response = client.post(
            "/performance/composites/twr",
            json=common_request,
        )
        inspection_response = client.post(
            "/performance/composites/inspect",
            json=common_request | {"inspection_id": "8d1e37d2-aeca-488c-bd43-77dbf6739103"},
        )

    for response in (twr_response, inspection_response):
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "COMPOSITE_FACT_SELECTION_INCOMPLETE"


def test_composite_twr_api_returns_degraded_reason_codes_for_non_ready_member_facts():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        facts = (
            _seed_fact("P1", "0.0100", "100.00"),
            _seed_fact("P2", "0.0300", "300.00", status="DEGRADED", reason_codes=["missing_final_valuation"]),
        )
        _complete_publication(*facts)

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


def test_composite_twr_api_preserves_selected_sequence_for_blocked_period():
    with TestClient(app) as client:
        composite_metadata_store.clear_all_records()
        _seed_definition()
        fact = _seed_fact(
            "P1",
            "0.0100",
            "0.00",
            restatement_version="correction-7",
            restatement_sequence=7,
        )
        _complete_publication(fact)

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
    assert payload["status"] == "BLOCKED"
    assert payload["periods"][0]["member_contributions"] == []
    assert payload["periods"][0]["restatement_sequence"] == 7


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
        facts = (_seed_fact("P1", "0.0100", "100.00"), _seed_fact("P2", "0.0300", "300.00"))
        _complete_publication(*facts)

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
