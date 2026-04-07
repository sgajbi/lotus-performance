from fastapi.testclient import TestClient

from main import app


class _RecordingStatefulInputService:
    def __init__(self) -> None:
        self.assignment_calls: list[dict[str, object]] = []
        self.market_series_calls: list[dict[str, object]] = []
        self.index_catalog_calls: list[dict[str, object]] = []

    async def get_benchmark_assignment(self, **kwargs):
        self.assignment_calls.append(kwargs)
        return 200, {"benchmark_id": "BMK_GLOBAL_60_40"}

    async def get_index_catalog(self, **kwargs):
        self.index_catalog_calls.append(kwargs)
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_GLOBAL_EQUITY",
                        "classification_labels": {"sector": "Global Equity", "asset_class": "Equity"},
                    },
                    {
                        "index_id": "IDX_GLOBAL_BONDS",
                        "classification_labels": {"sector": "Global Bonds", "asset_class": "Fixed Income"},
                    },
                ]
            },
        )

    async def get_benchmark_market_series(self, **kwargs):
        self.market_series_calls.append(kwargs)
        return (
            200,
            {
                "component_series": [
                    {
                        "index_id": "IDX_GLOBAL_EQUITY",
                        "points": [{"series_date": "2026-01-02", "component_weight": "0.60"}],
                    },
                    {
                        "index_id": "IDX_GLOBAL_BONDS",
                        "points": [{"series_date": "2026-01-02", "component_weight": "0.40"}],
                    },
                ],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            },
        )


def test_benchmark_exposure_context_api_returns_performance_aligned_view(monkeypatch):
    stateful_service = _RecordingStatefulInputService()
    monkeypatch.setattr(
        "app.api.endpoints.benchmark_exposure_context.build_stateful_input_service",
        lambda *, settings: stateful_service,
    )

    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-01-02",
        "window": {"start_date": "2026-01-02", "end_date": "2026-01-02"},
        "frequency": "DAILY",
        "reporting_currency": "USD",
        "grouping_dimensions": ["POSITION", "ASSET_CLASS"],
    }

    with TestClient(app) as client:
        response = client.post("/integration/benchmarks/exposure-context", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["source_service"] == "lotus-performance"
    assert body["metadata"]["source_system"] == "lotus-core"
    assert body["metadata"]["served_by"] == "lotus-performance"
    assert body["benchmark_id"] == "BMK_GLOBAL_60_40"
    assert {(row["grouping_dimension"], row["group_key"], row["weight"]) for row in body["rows"]} == {
        ("POSITION", "IDX_GLOBAL_EQUITY", "0.60"),
        ("POSITION", "IDX_GLOBAL_BONDS", "0.40"),
        ("ASSET_CLASS", "ASSET_CLASS_Equity", "0.60"),
        ("ASSET_CLASS", "ASSET_CLASS_Fixed Income", "0.40"),
    }
    assert stateful_service.assignment_calls[0]["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert stateful_service.market_series_calls[0]["series_fields"] == ["component_weight"]
    assert stateful_service.market_series_calls[0]["target_currency"] == "USD"


def test_benchmark_exposure_context_api_rejects_issuer_until_contract_exists() -> None:
    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-01-02",
        "window": {"start_date": "2026-01-02", "end_date": "2026-01-02"},
        "grouping_dimensions": ["ISSUER"],
    }

    with TestClient(app) as client:
        response = client.post("/integration/benchmarks/exposure-context", json=payload)

    assert response.status_code == 422
    assert "does not yet support" in response.text
