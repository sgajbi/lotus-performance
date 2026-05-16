# Benchmark Exposure Context Endpoint Certification

Status: certified for the endpoint audit loop.

Endpoint:

- `POST /integration/benchmarks/exposure-context`

## Purpose

Use benchmark exposure context when a downstream analytics service needs benchmark exposure history
aligned with lotus-performance benchmark return context. The current strategic consumer is
`lotus-risk` stateful active-risk attribution.

This endpoint is not a benchmark performance return endpoint. Use `POST /performance/benchmark` or
`POST /integration/returns/series` for benchmark return series. This endpoint returns benchmark
weights and classification context only.

## Ownership

lotus-core remains the system of record for:

- benchmark assignment;
- benchmark composition and market-series component weights;
- index catalog classification labels.

lotus-performance owns the derived, performance-aligned integration contract because active-risk
attribution needs benchmark exposures and benchmark returns on the same performance context.

## Certified Request Options

The certified v1 request contract covers:

- `portfolio_id` plus omitted `benchmark_id`, where lotus-performance resolves benchmark assignment
  through lotus-core;
- explicit `benchmark_id`, which bypasses benchmark assignment lookup;
- `as_of_date`;
- `window.start_date` and `window.end_date`;
- `frequency=DAILY`;
- optional `reporting_currency`;
- supported grouping dimensions `POSITION`, `SECTOR`, `ASSET_CLASS`, and `ISSUER`;
- issuer grouping sourced from `classification_labels.issuer_id` and `issuer_name` in lotus-core
  index catalog records;
- pagination through `page.page_size` and `page.page_token`.

`WEEKLY` and `MONTHLY` frequencies are intentionally rejected in v1. Downstream callers should not
assume lotus-performance resamples benchmark exposure history.

## Output Figure Tie-Outs

The certification suite checks every output family:

- top-level lineage fields `source_service=lotus-performance` and `contract_version=v1`;
- metadata lineage fields `source_system=lotus-core`, `served_by=lotus-performance`, and
  `contract_version=v1`;
- resolved `benchmark_id`, `benchmark_version`, `as_of_date`, `window`, `frequency`, and
  `reporting_currency`;
- retrieval counters for benchmark market-series and index catalog calls;
- `POSITION` rows carry `component_id`, `group_key`, `group_label`, and decimal `weight`;
- aggregate `SECTOR`, `ASSET_CLASS`, and `ISSUER` rows omit `component_id` and sum component
  weights by date and group;
- for a fully covered date, weights by grouping dimension sum to `1.0`;
- pagination returns a deterministic next-page token and no token on the final page.

Weights are decimal fractions, not percentages. A row weight of `0.60` means 60% benchmark exposure.

## Upstream Integration

The endpoint calls lotus-core query-control-plane analytics-input contracts through the shared
stateful input service:

- benchmark assignment when `benchmark_id` is omitted;
- benchmark market series with `series_fields=["component_weight"]`;
- targeted index catalog lookup only when aggregate dimensions need classification labels.

If only `POSITION` is requested, the endpoint does not fetch index catalog data. This keeps the
simple downstream path cheaper and avoids unnecessary upstream dependency.

## Downstream Consumers

Current strategic downstream consumer:

- `lotus-risk`
  - client: `src/app/integrations/lotus_performance_client.py`
  - adapter: `src/app/services/benchmark_exposure_history.py`
  - usage: stateful active-risk attribution fetches benchmark exposure context with
    `frequency=DAILY`, `page_size=1000`, and supported grouping dimensions including issuer.

`lotus-gateway` and `lotus-workbench` do not call this endpoint directly. They surface user-facing
active-risk issuer attribution only through governed risk and gateway contracts.

No duplicate downstream endpoint use was found. This endpoint remains the strategic integration
surface for performance-aligned benchmark exposure history.

## GitHub Issue Disposition

Open issue search found no endpoint-specific defects in:

- `sgajbi/lotus-performance`;
- `sgajbi/lotus-risk`;
- `sgajbi/lotus-gateway`.

Upstream benchmark component classification coverage is now aligned:

- `sgajbi/lotus-core#306` was fixed in lotus-core.
- canonical benchmark component indices now publish governed broad-market sector labels such as
  `broad_market_equity` and `broad_market_fixed_income`.
- lotus-performance consumes those source-owned labels as published rather than synthesizing local
  sector fallbacks.

## Live Canonical Proof

Local runtime proof was taken against `performance-analytics` on `http://127.0.0.1:8002` and
lotus-core query-control-plane on host port `8202`.

Request:

```json
{
  "portfolio_id": "PB_SG_GLOBAL_BAL_001",
  "benchmark_id": "BMK_PB_GLOBAL_BALANCED_60_40",
  "as_of_date": "2026-04-10",
  "window": { "start_date": "2026-04-10", "end_date": "2026-04-10" },
  "frequency": "DAILY",
  "reporting_currency": "USD",
  "grouping_dimensions": ["POSITION", "SECTOR", "ASSET_CLASS"],
  "page": { "page_size": 1000, "page_token": null }
}
```

Observed response:

- HTTP `200` synchronous response;
- `source_service=lotus-performance`;
- `contract_version=v1`;
- `benchmark_id=BMK_PB_GLOBAL_BALANCED_60_40`;
- `row_count=5`;
- `POSITION` weight sum for `2026-04-10` is `1.0`;
- `ASSET_CLASS` weight sum for `2026-04-10` is `1.0`;
- `SECTOR` weight sum for `2026-04-10` is `1.0`, with governed broad-market sector rows sourced
  from lotus-core index catalog metadata.

Relevant upstream catalog slice:

```json
[
  {
    "index_id": "IDX_GLOBAL_BOND_TR",
    "classification_labels": {
      "asset_class": "fixed_income",
      "sector": "broad_market_fixed_income",
      "region": "global"
    }
  },
  {
    "index_id": "IDX_GLOBAL_EQUITY_TR",
    "classification_labels": {
      "asset_class": "equity",
      "sector": "broad_market_equity",
      "region": "global"
    }
  }
]
```

## Test Pyramid

Coverage added or confirmed:

- model validation tests for inverted windows, empty dimensions, issuer gating, and non-daily
  frequency rejection;
- service tests for assignment resolution, explicit benchmark bypass, grouping aggregation,
  pagination, unsupported shapes, upstream failure mapping, and retrieval metadata;
- API integration tests for lineage metadata, every supported grouping dimension, row weight
  semantics, pagination, issuer rejection, and frequency rejection;
- OpenAPI regression requiring purpose text, source-of-record wording, request/response field
  descriptions, and examples;
- downstream lotus-risk unit tests verifying request payload shape, lineage validation, pagination,
  empty-payload handling, invalid weights, and active-risk attribution date-grid checks.

## Certification Commands

```bash
python -m pytest tests/integration/test_benchmark_exposure_context_api.py tests/unit/services/test_benchmark_exposure_context_service.py tests/unit/app/test_benchmark_exposure_context_models.py tests/unit/app/test_benchmark_exposure_context_endpoint.py tests/unit/app/test_benchmark_exposure_context_openapi_contract.py -q
python -m ruff check app/api/endpoints/benchmark_exposure_context.py app/models/benchmark_exposure_context.py app/services/benchmark_exposure_context_service.py tests/integration/test_benchmark_exposure_context_api.py tests/unit/app/test_benchmark_exposure_context_openapi_contract.py
python -m ruff format --check app/api/endpoints/benchmark_exposure_context.py app/models/benchmark_exposure_context.py app/services/benchmark_exposure_context_service.py tests/integration/test_benchmark_exposure_context_api.py tests/unit/app/test_benchmark_exposure_context_openapi_contract.py
python -m mypy app/api/endpoints/benchmark_exposure_context.py app/models/benchmark_exposure_context.py app/services/benchmark_exposure_context_service.py
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
```
