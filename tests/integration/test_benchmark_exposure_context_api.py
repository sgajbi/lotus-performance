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


class _MalformedRetrievalMetadataStatefulInputService(_RecordingStatefulInputService):
    async def get_benchmark_market_series(self, **kwargs):
        status_code, payload = await super().get_benchmark_market_series(**kwargs)
        payload["retrieval_metadata"] = {"chunk_count": "two", "page_count": 2.5}
        return status_code, payload


class _PartialExposureStatefulInputService(_RecordingStatefulInputService):
    async def get_benchmark_market_series(self, **kwargs):
        self.market_series_calls.append(kwargs)
        return (
            200,
            {
                "component_series": [
                    {
                        "index_id": "IDX_GLOBAL_EQUITY",
                        "points": [{"series_date": "2026-01-02", "component_weight": "0.30"}],
                    },
                    {
                        "index_id": "IDX_GLOBAL_BONDS",
                        "points": [{"series_date": "2026-01-02"}],
                    },
                    {
                        "index_id": "IDX_GLOBAL_REAL_ASSETS",
                        "points": [{"series_date": "2026-01-02", "component_weight": "0.40"}],
                    },
                    {
                        "index_id": "IDX_GLOBAL_CASH",
                        "points": [{"series_date": "2026-01-02", "component_weight": "0"}],
                    },
                ],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            },
        )


class _EmptyUsableExposureStatefulInputService(_RecordingStatefulInputService):
    async def get_benchmark_market_series(self, **kwargs):
        self.market_series_calls.append(kwargs)
        return (
            200,
            {"component_series": [{"index_id": "IDX_GLOBAL_BONDS", "points": [{"series_date": "2026-01-02"}]}]},
        )


class _MutableExposureStatefulInputService(_RecordingStatefulInputService):
    equity_weight = "0.60"
    include_unusable_component = False
    empty_source = False

    async def get_benchmark_market_series(self, **kwargs):
        status_code, payload = await super().get_benchmark_market_series(**kwargs)
        if self.empty_source:
            payload["component_series"] = []
            return status_code, payload
        payload["component_series"][0]["points"][0]["component_weight"] = self.equity_weight
        if self.include_unusable_component:
            payload["component_series"].append({"index_id": "IDX_UNUSABLE", "points": [{"series_date": "2026-01-02"}]})
        return status_code, payload


def test_benchmark_exposure_context_api_returns_performance_aligned_view(monkeypatch):
    stateful_service = _RecordingStatefulInputService()
    monkeypatch.setattr(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
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
    assert body["page"]["next_page_token"].startswith("v1.2.")
    assert body["page"]["continuation_consistency"] == "source_bound"
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
    assert next_body["page"]["continuation_consistency"] == "source_bound"
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


def test_benchmark_exposure_continuation_refuses_changed_economics_and_tenant(monkeypatch) -> None:
    stateful_service = _MutableExposureStatefulInputService()
    monkeypatch.setattr(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
        lambda *, settings: stateful_service,
    )
    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-01-02",
        "window": {"start_date": "2026-01-02", "end_date": "2026-01-02"},
        "frequency": "DAILY",
        "reporting_currency": "USD",
        "grouping_dimensions": ["POSITION", "SECTOR"],
        "page": {"page_size": 2, "page_token": None},
    }
    with TestClient(app) as client:
        first = client.post(
            "/integration/benchmarks/exposure-context",
            json=payload,
            headers={"X-Tenant-Id": "tenant-a"},
        )
        assert first.status_code == 200
        continuation = first.json()["page"]["next_page_token"]
        assert continuation is not None
        next_payload = {**payload, "page": {"page_size": 2, "page_token": continuation}}

        unchanged = client.post(
            "/integration/benchmarks/exposure-context",
            json=next_payload,
            headers={"X-Tenant-Id": "tenant-a"},
        )
        assert unchanged.status_code == 200

        stateful_service.equity_weight = "0.600"
        equivalent_representation = client.post(
            "/integration/benchmarks/exposure-context",
            json=next_payload,
            headers={"X-Tenant-Id": "tenant-a"},
        )
        assert equivalent_representation.status_code == 200

        stateful_service.equity_weight = "0.55"
        restated = client.post(
            "/integration/benchmarks/exposure-context",
            json=next_payload,
            headers={"X-Tenant-Id": "tenant-a"},
        )
        assert restated.status_code == 409
        assert restated.json()["error_code"] == "BENCHMARK_EXPOSURE_PAGE_SOURCE_CHANGED"

        stateful_service.empty_source = True
        emptied = client.post(
            "/integration/benchmarks/exposure-context",
            json=next_payload,
            headers={"X-Tenant-Id": "tenant-a"},
        )
        assert emptied.status_code == 409
        stateful_service.empty_source = False

        stateful_service.equity_weight = "0.60"
        foreign_tenant = client.post(
            "/integration/benchmarks/exposure-context",
            json=next_payload,
            headers={"X-Tenant-Id": "tenant-b"},
        )
        assert foreign_tenant.status_code == 409

        changed_window = client.post(
            "/integration/benchmarks/exposure-context",
            json={**next_payload, "window": {"start_date": "2026-01-01", "end_date": "2026-01-02"}},
            headers={"X-Tenant-Id": "tenant-a"},
        )
        assert changed_window.status_code == 409

        malformed = client.post(
            "/integration/benchmarks/exposure-context",
            json={**payload, "page": {"page_size": 2, "page_token": "v1.2.invalid"}},
            headers={"X-Tenant-Id": "tenant-a"},
        )
        assert malformed.status_code == 422


def test_benchmark_exposure_continuation_binds_omission_quality(monkeypatch) -> None:
    stateful_service = _MutableExposureStatefulInputService()
    monkeypatch.setattr(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
        lambda *, settings: stateful_service,
    )
    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-01-02",
        "window": {"start_date": "2026-01-02", "end_date": "2026-01-02"},
        "grouping_dimensions": ["POSITION", "SECTOR"],
        "page": {"page_size": 2, "page_token": None},
    }
    with TestClient(app) as client:
        first = client.post("/integration/benchmarks/exposure-context", json=payload)
        assert first.status_code == 200
        continuation = first.json()["page"]["next_page_token"]
        assert continuation is not None
        stateful_service.include_unusable_component = True
        changed_quality = client.post(
            "/integration/benchmarks/exposure-context",
            json={**payload, "page": {"page_size": 2, "page_token": continuation}},
        )
    assert changed_quality.status_code == 409


def test_benchmark_exposure_context_api_degrades_malformed_retrieval_metadata(monkeypatch):
    stateful_service = _MalformedRetrievalMetadataStatefulInputService()
    monkeypatch.setattr(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
        lambda *, settings: stateful_service,
    )

    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-01-02",
        "window": {"start_date": "2026-01-02", "end_date": "2026-01-02"},
        "frequency": "DAILY",
        "grouping_dimensions": ["POSITION"],
    }

    with TestClient(app) as client:
        response = client.post("/integration/benchmarks/exposure-context", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["rows"]
    assert body["metadata"]["retrieval_metadata"] == {
        "benchmark_market_series_chunk_count": 0,
        "benchmark_market_series_page_count": 0,
        "index_catalog_page_count": 0,
    }
    assert body["metadata"]["retrieval_metadata_quality"] == {
        "status": "degraded",
        "warning_count": 2,
        "reason_codes": ["MALFORMED_UPSTREAM_RETRIEVAL_METADATA_COUNT"],
        "invalid_fields": ["retrieval_metadata.chunk_count", "retrieval_metadata.page_count"],
    }


def test_benchmark_exposure_context_api_qualifies_partial_economics_on_every_page(monkeypatch) -> None:
    stateful_service = _PartialExposureStatefulInputService()
    monkeypatch.setattr(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
        lambda *, settings: stateful_service,
    )
    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-01-02",
        "window": {"start_date": "2026-01-02", "end_date": "2026-01-02"},
        "frequency": "DAILY",
        "grouping_dimensions": ["POSITION"],
        "page": {"page_size": 2, "page_token": None},
    }

    with TestClient(app) as client:
        first_response = client.post("/integration/benchmarks/exposure-context", json=payload)
        second_response = client.post(
            "/integration/benchmarks/exposure-context",
            json={**payload, "page": {"page_size": 2, "page_token": "2"}},
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_body = first_response.json()
    second_body = second_response.json()
    expected_quality = {
        "status": "incomplete",
        "omitted_component_count": 0,
        "omitted_point_count": 1,
        "reason_codes": ["MISSING_COMPONENT_WEIGHT"],
        "omissions": [
            {
                "component_id": "IDX_GLOBAL_BONDS",
                "series_date": "2026-01-02",
                "reason_code": "MISSING_COMPONENT_WEIGHT",
            }
        ],
        "omissions_truncated": False,
    }
    assert first_body["metadata"]["exposure_source_quality"] == expected_quality
    assert second_body["metadata"]["exposure_source_quality"] == expected_quality
    assert second_body["page"]["continuation_consistency"] == "legacy_offset_unbound"
    assert {row["weight"] for row in [*first_body["rows"], *second_body["rows"]]} == {"0.30", "0.40", "0"}


def test_benchmark_exposure_context_api_refuses_empty_usable_economics(monkeypatch) -> None:
    stateful_service = _EmptyUsableExposureStatefulInputService()
    monkeypatch.setattr(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
        lambda *, settings: stateful_service,
    )
    payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": "2026-01-02",
        "window": {"start_date": "2026-01-02", "end_date": "2026-01-02"},
        "frequency": "DAILY",
        "grouping_dimensions": ["POSITION"],
    }

    with TestClient(app) as client:
        response = client.post("/integration/benchmarks/exposure-context", json=payload)

    assert response.status_code == 422
    assert "No usable benchmark exposure rows returned" in response.text


def test_benchmark_exposure_context_api_returns_issuer_groups(monkeypatch) -> None:
    stateful_service = _RecordingStatefulInputService()
    monkeypatch.setattr(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
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
