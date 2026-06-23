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
                        "classification_labels": {
                            "sector": "Global Equity",
                            "asset_class": "Equity",
                            "issuer_id": "ISSUER_GLOBAL_EQUITY",
                            "issuer_name": "Global Equity Issuer Basket",
                        },
                    },
                    {
                        "index_id": "IDX_GLOBAL_BONDS",
                        "classification_labels": {
                            "sector": "Global Bonds",
                            "asset_class": "Fixed Income",
                            "issuer_id": "ISSUER_GLOBAL_BONDS",
                            "issuer_name": "Global Bond Issuer Basket",
                        },
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
        "grouping_dimensions": ["POSITION", "SECTOR", "ASSET_CLASS", "ISSUER"],
        "page": {"page_size": 2, "page_token": None},
    }

    with TestClient(app) as client:
        response = client.post(
            "/integration/benchmarks/exposure-context",
            json=payload,
            headers={"X-Correlation-Id": "corr-benchmark-exposure-api"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["source_service"] == "lotus-performance"
    assert body["contract_version"] == "v1"
    assert body["metadata"]["source_system"] == "lotus-core"
    assert body["metadata"]["served_by"] == "lotus-performance"
    assert body["metadata"]["contract_version"] == "v1"
    assert body["metadata"]["correlation_id"] == "corr-benchmark-exposure-api"
    assert body["metadata"]["retrieval_metadata"] == {
        "benchmark_market_series_chunk_count": 1,
        "benchmark_market_series_page_count": 1,
        "index_catalog_page_count": 1,
    }
    assert body["benchmark_id"] == "BMK_GLOBAL_60_40"
    assert body["benchmark_version"] == "2026-01-02"
    assert body["as_of_date"] == "2026-01-02"
    assert body["frequency"] == "DAILY"
    assert body["reporting_currency"] == "USD"
    assert body["window"] == {"start_date": "2026-01-02", "end_date": "2026-01-02"}
    assert body["page"]["next_page_token"] == "2"
    assert {(row["grouping_dimension"], row["group_key"], row["weight"]) for row in body["rows"]} == {
        ("ASSET_CLASS", "ASSET_CLASS_Equity", "0.60"),
        ("ASSET_CLASS", "ASSET_CLASS_Fixed Income", "0.40"),
    }
    next_payload = {**payload, "page": {"page_size": 10, "page_token": body["page"]["next_page_token"]}}
    with TestClient(app) as client:
        next_response = client.post("/integration/benchmarks/exposure-context", json=next_payload)

    assert next_response.status_code == 200
    next_body = next_response.json()
    assert next_body["page"].get("next_page_token") is None
    assert {(row["grouping_dimension"], row["group_key"], row["weight"]) for row in next_body["rows"]} == {
        ("POSITION", "IDX_GLOBAL_EQUITY", "0.60"),
        ("POSITION", "IDX_GLOBAL_BONDS", "0.40"),
        ("ISSUER", "ISSUER_ISSUER_GLOBAL_EQUITY", "0.60"),
        ("ISSUER", "ISSUER_ISSUER_GLOBAL_BONDS", "0.40"),
        ("SECTOR", "SECTOR_Global Equity", "0.60"),
        ("SECTOR", "SECTOR_Global Bonds", "0.40"),
    }
    weights_by_dimension = {}
    for row in [*body["rows"], *next_body["rows"]]:
        key = (row["valuation_date"], row["grouping_dimension"])
        weights_by_dimension[key] = weights_by_dimension.get(key, 0.0) + float(row["weight"])
        if row["grouping_dimension"] == "POSITION":
            assert row["component_id"] == row["group_key"]
        else:
            assert row.get("component_id") is None
    assert weights_by_dimension == {
        ("2026-01-02", "POSITION"): 1.0,
        ("2026-01-02", "SECTOR"): 1.0,
        ("2026-01-02", "ASSET_CLASS"): 1.0,
        ("2026-01-02", "ISSUER"): 1.0,
    }
    assert stateful_service.assignment_calls[0]["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert stateful_service.market_series_calls[0]["series_fields"] == ["component_weight"]
    assert stateful_service.market_series_calls[0]["target_currency"] == "USD"


def test_benchmark_exposure_context_api_returns_issuer_groups(monkeypatch) -> None:
    stateful_service = _RecordingStatefulInputService()
    monkeypatch.setattr(
        "app.api.endpoints.benchmark_exposure_context.build_stateful_input_service",
        lambda *, settings: stateful_service,
    )
    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-01-02",
        "window": {"start_date": "2026-01-02", "end_date": "2026-01-02"},
        "grouping_dimensions": ["ISSUER"],
    }

    with TestClient(app) as client:
        response = client.post("/integration/benchmarks/exposure-context", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert {(row["group_key"], row["group_label"], row["weight"]) for row in body["rows"]} == {
        ("ISSUER_ISSUER_GLOBAL_EQUITY", "Global Equity Issuer Basket", "0.60"),
        ("ISSUER_ISSUER_GLOBAL_BONDS", "Global Bond Issuer Basket", "0.40"),
    }


def test_benchmark_exposure_context_api_rejects_non_daily_frequency() -> None:
    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-01-02",
        "window": {"start_date": "2026-01-02", "end_date": "2026-01-02"},
        "frequency": "MONTHLY",
        "grouping_dimensions": ["POSITION"],
    }

    with TestClient(app) as client:
        response = client.post("/integration/benchmarks/exposure-context", json=payload)

    assert response.status_code == 422
    assert "frequency=DAILY only" in response.text
