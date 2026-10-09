from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_authority_helpers import install_test_authorities
from tests.composite_linked_contribution_helpers import (
    LINKED_PATH,
    assert_or13,
    linked_packet,
    linked_request,
    publish_pairs,
)
from tests.integration.test_composite_provider_materialization_api import HEADERS, install_provider_wires


@pytest.fixture(autouse=True)
def linked_database(monkeypatch, tmp_path):
    url = "sqlite:///" + (tmp_path / "linked.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", url)
    assert apply_durable_schema(database_url=url).status == "passed"
    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", "https://manage.test")


def _install(monkeypatch, pairs):
    packets, wires = map(list, zip(*pairs, strict=True))
    install_test_authorities(monkeypatch, packets)
    install_provider_wires(monkeypatch, packets, wires)


def test_registered_linked_or13_correction_pins_and_twr_compatibility(monkeypatch):
    pairs = [linked_packet(month) for month in (1, 2)]
    correction = linked_packet(1, corrected=True)
    _install(monkeypatch, [*pairs, correction])
    with TestClient(app, headers=HEADERS) as client:
        commands = publish_pairs(client, pairs)
        payload = linked_request(commands)
        result = client.post(LINKED_PATH, json=payload)
        assert result.status_code == 200, result.text
        assert_or13(result.json())
        periods = result.json()["periods"]
        for offset in (0, 2):
            assert sum((Decimal(row["weight"]) for row in periods[offset : offset + 2]), Decimal(0)) == 1
        assert [Decimal(row["contribution"]) for row in periods] == list(
            map(Decimal, (".025", "-.015", ".005", ".015"))
        )
        twr_payload = {key: value for key, value in payload.items() if key not in ("method", "metric_id")}
        twr = client.post("/performance/composites/twr", json=twr_payload)
        assert twr.status_code == 200
        assert Decimal(twr.json()["cumulative_return"]) == Decimal(".0302")
        original_windows = result.json()["selection_manifest"]["windows"]
        assert original_windows == twr.json()["selection_manifest"]["windows"]
        corrected = publish_pairs(client, [correction], sequence_start=3)[0]
        assert client.post(LINKED_PATH, json=payload).json() == result.json()
        revised = client.post(LINKED_PATH, json=linked_request([corrected, commands[1]]))
        assert revised.status_code == 200, revised.text
        assert Decimal(revised.json()["cumulative_return"]) == Decimal(".0404")
        assert (
            revised.json()["selection_manifest"]["calculation_fingerprint"]
            != result.json()["selection_manifest"]["calculation_fingerprint"]
        )


@pytest.mark.parametrize("excluded", [False, True])
def test_registered_linked_member_entry_exit_and_authoritative_exclusion(monkeypatch, excluded):
    pairs = [linked_packet(1), linked_packet(2, member_b="external-member-c", excluded_b=excluded)]
    _install(monkeypatch, pairs)
    with TestClient(app, headers=HEADERS) as client:
        commands = publish_pairs(client, pairs)
        result = client.post(LINKED_PATH, json=linked_request(commands))
        assert result.status_code == 200, result.text
        body = result.json()
        counts = {row["portfolio_id"]: row["participating_period_count"] for row in body["members"]}
        assert counts == (
            {"external-member-a": 2, "external-member-b": 1}
            if excluded
            else {"external-member-a": 2, "external-member-b": 1, "external-member-c": 1}
        )
        expected = Decimal(".0201") if excluded else Decimal(".0302")
        assert abs(Decimal(body["cumulative_return"]) - expected) < Decimal("1e-70")
        assert abs(Decimal(body["reconciliation_difference"])) < Decimal("1e-70")


@pytest.mark.parametrize(
    "fault", ["gap", "order", "duplicate", "foreign", "fee", "currency", "method", "missing", "unselected", "override"]
)
def test_registered_linked_refuses_unavailable_selection(monkeypatch, fault):
    pairs = [linked_packet(month, missing_member=fault == "missing" and month == 2) for month in (1, 2, 3)]
    _install(monkeypatch, pairs)
    with TestClient(app, headers=HEADERS) as client:
        commands = publish_pairs(client, pairs)
        payload = linked_request(commands)
        headers = HEADERS
        if fault == "gap":
            payload["materialization_ids"].pop(1)
        elif fault == "order":
            payload["materialization_ids"].reverse()
        elif fault == "duplicate":
            payload["materialization_ids"][1] = payload["materialization_ids"][0]
        elif fault == "foreign":
            headers = {**HEADERS, "X-Tenant-Id": "synthetic-tenant-b"}
        elif fault == "fee":
            payload["return_view"] = "NET_ACTUAL"
        elif fault == "currency":
            payload["reporting_currency"] = "EUR"
        elif fault == "method":
            payload["method"] = "RAW"
        elif fault == "unselected":
            payload.pop("materialization_ids")
        elif fault == "override":
            payload["composite_return_override"] = ".05"
        result = client.post(LINKED_PATH, json=payload, headers=headers)
        assert result.status_code == (
            409 if fault in ("gap", "missing") else 404 if fault == "foreign" else 422
        ), result.text
        assert "members" not in result.json() and "cumulative_return" not in result.json()


@pytest.mark.parametrize(
    "returns,expected",
    [
        (("0", "0"), "0"),
        ((".000000000000000001", "0"), ".0000000000000000005"),
        (("-1", "-1"), None),
        (("-1.1", "-1.1"), None),
    ],
)
def test_registered_linked_zero_near_zero_and_log_domain(monkeypatch, returns, expected):
    pairs = [linked_packet(1, returns=returns)]
    _install(monkeypatch, pairs)
    with TestClient(app, headers=HEADERS) as client:
        commands = publish_pairs(client, pairs)
        if expected is not None:
            retained = client.get(f"/performance/composites/materializations/{commands[0].materialization_id}").json()
            assert retained["state"] == "COMPLETE", [
                (row["reason_code"], row.get("reason_codes")) for row in retained["members"]
            ]
        payload = linked_request(commands)
        result = client.post(LINKED_PATH, json=payload)
        if expected is None:
            # Below -100% observations are already refused by the retained worker.
            assert result.status_code == (409 if returns[0] == "-1.1" else 422), result.text
            assert result.json()["error_code"] == (
                "REQUIRED_PERIOD_UNAVAILABLE" if returns[0] == "-1.1" else "COMPOSITE_CARINO_LOG_DOMAIN_REFUSED"
            )
        else:
            assert result.status_code == 200, result.text
            assert Decimal(result.json()["cumulative_return"]) == Decimal(expected)
