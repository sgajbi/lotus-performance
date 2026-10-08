"""Registered reads over independently retained normalized reporting projections."""

import csv
from dataclasses import replace
from io import StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_materialization_repository import CompositeMaterializationStore
from app.core.config import get_settings
from app.models.composite_materialization import CompositeMaterializationState
from app.services.composite_materialization.application import _publish
from app.services.composite_metadata_store import CompositeMetadataStore
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_annual_fx_helpers import normalized_month_record
from tests.unit.services.test_composite_annual_dispersion_service import month_record


def publish_projection(url, record):
    ledger, facts = CompositeMaterializationStore(url), CompositeMetadataStore(url)
    try:
        ledger.register(record.command, tenant_id="tenant-a", actor_id="operator")
        retained = ledger.save(
            record.command.materialization_id,
            tenant_id="tenant-a",
            expected_revision=0,
            source=record.source,
            outcomes=record.outcomes,
            state=CompositeMaterializationState.PUBLISHING,
            reason_code=None,
        )
        _publish(retained, tenant_id="tenant-a", ledger=ledger, facts=facts, fence=lambda: None)
    finally:
        ledger.close()
        facts.close()


def request_for(record):
    return {
        "composite_id": record.command.composite_id,
        "period_start": str(record.command.period_start),
        "period_end": str(record.command.period_end),
        "return_view": str(record.command.return_view),
    }


def response_currency(endpoint, data):
    if endpoint.endswith("twr"):
        return data["periods"][0]["reporting_currency"]
    artifact = next(item for item in data["artifacts"] if item["artifact_name"] == "composite_returns.csv")
    rows = list(csv.DictReader(StringIO(artifact["artifact_content"])))
    assert rows, "The selected reporting projection must retain its financial rows."
    return rows[0]["reporting_currency"]


@pytest.mark.parametrize("endpoint", ["/performance/composites/twr", "/performance/composites/inspect"])
@pytest.mark.parametrize("same_window", [True, False, "partial"])
def test_registered_projection_defaults_are_scoped_or_require_explicit_currency(
    monkeypatch, tmp_path, endpoint, same_window, database_url=None
):
    from types import SimpleNamespace

    from tests.composite_currency_normalization_helpers import synthetic_fx_verification

    monkeypatch.setattr(
        "app.ports.composite_currency_normalization.composite_fx_receipt_verifier",
        lambda: SimpleNamespace(verify=synthetic_fx_verification),
    )
    url = database_url or "sqlite:///" + (tmp_path / "projections.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    usd = normalized_month_record(month_record(1))
    gbp_template = month_record(1 if same_window else 2)
    command = gbp_template.command.model_copy(
        update={
            "materialization_id": uuid4(),
            "restatement_sequence": 13,
            "reporting_currency": "GBP",
            "member_calculations": [
                ref.model_copy(update={"calculation_id": uuid4()}) for ref in gbp_template.command.member_calculations
            ],
        }
    )
    if same_window == "partial":
        command = command.model_copy(update={"period_start": command.period_start.replace(day=15)})
    outcomes = [
        item.model_copy(
            update={
                "fact": item.fact.model_copy(
                    update={"restatement_sequence": 13, "restatement_version": str(command.materialization_id)}
                )
            }
        )
        for item in gbp_template.outcomes
    ]
    gbp = normalized_month_record(replace(gbp_template, command=command, outcomes=outcomes))
    publish_projection(url, usd)
    publish_projection(url, gbp)
    with TestClient(app, headers={"X-Tenant-Id": "tenant-a"}) as client:
        omitted = client.post(endpoint, json=request_for(usd))
        if same_window is True:
            assert omitted.status_code == 409, omitted.text
            assert omitted.json()["detail"]["code"] == "COMPOSITE_FACT_SELECTION_INCOMPLETE"
        else:
            assert omitted.status_code == 200, omitted.text
            assert response_currency(endpoint, omitted.json()) == "USD"
        for record in (usd, gbp):
            explicit = client.post(
                endpoint, json={**request_for(record), "reporting_currency": record.command.reporting_currency}
            )
            assert explicit.status_code == 200, explicit.text
            assert response_currency(endpoint, explicit.json()) == record.command.reporting_currency
            sequenced = client.post(
                endpoint, json={**request_for(record), "restatement_sequence": record.command.restatement_sequence}
            )
            assert sequenced.status_code == 200, sequenced.text
            assert response_currency(endpoint, sequenced.json()) == record.command.reporting_currency
            pinned = client.post(
                "/performance/composites/twr",
                json={**request_for(record), "materialization_ids": [str(record.command.materialization_id)]},
            )
            assert pinned.status_code == 200, pinned.text
            assert pinned.json()["periods"][0]["reporting_currency"] == record.command.reporting_currency
        foreign = client.post(endpoint, json=request_for(usd), headers={"X-Tenant-Id": "tenant-b"})
        assert foreign.status_code == 404
