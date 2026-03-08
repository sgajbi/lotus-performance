# tests/integration/test_attribution_api.py
import pytest
from fastapi.testclient import TestClient

from core.periods import ResolvedPeriod
from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from main import app
from tests.conftest import drain_lineage_queue


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_attribution_endpoint_by_instrument_happy_path(client):
    """Tests the /performance/attribution endpoint end-to-end with a valid 'by_instrument' payload."""
    payload = {
        "portfolio_id": "ATTRIB_BY_INST_01",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1018.5}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"sector": "Tech"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612}],
            },
            {
                "instrument_id": "JNJ",
                "meta": {"sector": "Health"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 406.5}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 0.5}],
            },
            {
                "key": {"sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.5}],
            },
        ],
    }

    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    response_data = response.json()["results_by_period"]["ITD"]
    assert response_data["reconciliation"]["total_active_return"] == pytest.approx(0.1)
    level = response_data["levels"][0]
    tech_group = next(g for g in level["groups"] if g["key"]["sector"] == "Tech")
    assert tech_group["selection"] == pytest.approx(0.25)


def test_attribution_lineage_flow(client):
    """Tests that lineage is correctly captured for an attribution request."""
    payload = {
        "portfolio_id": "ATTRIB_LINEAGE_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.02, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    attrib_response = client.post("/performance/attribution", json=payload)
    assert attrib_response.status_code == 200
    calculation_id = attrib_response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1

    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200
    lineage_data = lineage_response.json()

    assert lineage_data["calculation_type"] == "Attribution"
    assert "aligned_panel.csv" in lineage_data["artifacts"]
    assert "single_period_effects.csv" in lineage_data["artifacts"]


def test_attribution_endpoint_hierarchical(client):
    """Tests multi-level hierarchical attribution, ensuring bottom-up aggregation is correct."""
    payload = {
        "portfolio_id": "HIERARCHY_01",
        "mode": "by_instrument",
        "group_by": ["assetClass", "sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020}],
        },
        "instruments_data": [
            {
                "instrument_id": "AAPL",
                "meta": {"assetClass": "Equity", "sector": "Tech"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408}],
            },
            {
                "instrument_id": "JNJ",
                "meta": {"assetClass": "Equity", "sector": "Health"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 300, "end_mv": 303}],
            },
            {
                "instrument_id": "UST",
                "meta": {"assetClass": "Bond", "sector": "Government"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 300, "end_mv": 309}],
            },
        ],
        "benchmark_groups_data": [
            {
                "key": {"assetClass": "Equity", "sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.4}],
            },
            {
                "key": {"assetClass": "Equity", "sector": "Health"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 0.3}],
            },
            {
                "key": {"assetClass": "Bond", "sector": "Government"},
                "observations": [{"date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.3}],
            },
        ],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["ITD"]
    assert len(data["levels"]) == 2
    level_ac = data["levels"][0]
    level_sector = data["levels"][1]
    equity_ac_effects = next(g for g in level_ac["groups"] if g["key"]["assetClass"] == "Equity")
    tech_sector_effects = next(g for g in level_sector["groups"] if g["key"]["sector"] == "Tech")
    health_sector_effects = next(g for g in level_sector["groups"] if g["key"]["sector"] == "Health")
    assert equity_ac_effects["allocation"] == pytest.approx(
        tech_sector_effects["allocation"] + health_sector_effects["allocation"]
    )
    assert equity_ac_effects["selection"] == pytest.approx(
        tech_sector_effects["selection"] + health_sector_effects["selection"]
    )


def test_attribution_endpoint_currency_attribution(client):
    """Tests the Karnosky-Singer currency attribution model end-to-end."""
    payload = {
        "portfolio_id": "FX_ATTRIB_01",
        "mode": "by_instrument",
        "group_by": ["currency"],
        "linking": "none",
        "frequency": "daily",
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "GROSS",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 103.02}],
        },
        "instruments_data": [
            {
                "instrument_id": "EUR_ASSET",
                "meta": {"currency": "EUR"},
                "valuation_points": [
                    {"day": 1, "perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0}
                ],  # 2% local return
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"currency": "EUR"},
                "observations": [
                    {
                        "date": "2025-01-01",
                        "weight_bop": 1.0,
                        "return_local": 0.015,  # 1.5% local return
                        "return_fx": 0.01,  # 1% fx return
                        "return_base": 0.02515,  # (1.015 * 1.01) - 1
                    }
                ],
            }
        ],
        "fx": {
            "rates": [
                {"date": "2024-12-31", "ccy": "EUR", "rate": 1.00},
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.01},  # 1% fx return
            ]
        },
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["ITD"]

    assert "currency_attribution" in data
    assert data["currency_attribution"] is not None
    eur_effects = data["currency_attribution"][0]["effects"]

    assert eur_effects["local_allocation"] == pytest.approx(0.0)
    assert eur_effects["local_selection"] == pytest.approx(0.5)
    assert eur_effects["currency_allocation"] == pytest.approx(0.0)
    assert eur_effects["currency_selection"] == pytest.approx(0.005)
    assert eur_effects["total_effect"] == pytest.approx(0.505)

    calculation_id = response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1
    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200
    lineage_data = lineage_response.json()
    # --- START FIX: Update assertion to expect period-prefixed artifact name ---
    assert "ITD_currency_attribution_effects.csv" in lineage_data["artifacts"]
    # --- END FIX ---


@pytest.mark.parametrize(
    "error_class, expected_status",
    [
        (InvalidEngineInputError, 400),
        (EngineCalculationError, 500),
        (ValueError, 400),
        (NotImplementedError, 400),
        (Exception, 500),
    ],
)
def test_attribution_endpoint_error_handling(client, mocker, error_class, expected_status):
    """Tests that the attribution endpoint correctly handles engine exceptions."""
    mocker.patch("app.api.endpoints.performance.run_attribution_calculations", side_effect=error_class("Test Error"))
    payload = {
        "portfolio_id": "ERROR",
        "mode": "by_group",
        "group_by": ["sector"],
        "benchmark_groups_data": [],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == expected_status
    assert "detail" in response.json()


def test_attribution_endpoint_returns_400_when_no_resolved_periods(client, mocker):
    """Tests explicit 400 path when period resolution yields no valid periods."""
    mocker.patch("app.api.endpoints.performance.resolve_periods", return_value=[])
    payload = {
        "portfolio_id": "ATTRIB_NO_PERIODS",
        "mode": "by_group",
        "group_by": ["sector"],
        "benchmark_groups_data": [],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["monthly"]}],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "No valid periods could be resolved."


def test_attribution_endpoint_skips_empty_period_slice(client, mocker):
    """Tests empty-slice branch where a resolved period has no matching effect rows."""
    mocker.patch(
        "app.api.endpoints.performance.resolve_periods",
        return_value=[
            ResolvedPeriod(name="ITD", start_date="2025-01-01", end_date="2025-01-31"),
            ResolvedPeriod(name="MTD", start_date="2025-02-01", end_date="2025-02-28"),
        ],
    )
    payload = {
        "portfolio_id": "ATTRIB_EMPTY_SLICE",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "monthly",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [
            {"period": "ITD", "frequencies": ["monthly"]},
            {"period": "MTD", "frequencies": ["monthly"]},
        ],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.02, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-31", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }
    response = client.post("/performance/attribution", json=payload)
    assert response.status_code == 200
    results = response.json()["results_by_period"]
    assert "ITD" in results
    assert "MTD" not in results
