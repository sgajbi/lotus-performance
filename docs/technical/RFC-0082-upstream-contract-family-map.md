# RFC-0082 Upstream Contract Family Map

This document records how `lotus-performance` consumes upstream `lotus-core` contracts under platform
RFC-0082.

It is consumer-conformance evidence for:

1. `C:/Users/Sandeep/projects/lotus-platform/rfcs/RFC-0082-lotus-core-domain-authority-and-analytics-serving-boundary-hardening.md`
2. `C:/Users/Sandeep/projects/lotus-core/docs/architecture/RFC-0082-contract-family-inventory.md`

## Current Integration Posture

`lotus-performance` remains the performance analytics authority. It owns time-weighted return,
money-weighted return, benchmark analytics, contribution, attribution, returns-series integration,
execution lifecycle, and lineage.

`lotus-core` provides governed source data for stateful performance analytics. `lotus-performance`
does not ask `lotus-core` to compute performance, attribution, contribution, benchmark analytics,
or risk-adjusted analytics.

Current transport posture remains REST/OpenAPI through `CORE_CONTROL_PLANE_BASE_URL` for stateful
analytics-input contracts. `CORE_QUERY_BASE_URL` is a deprecated compatibility fallback only when
`CORE_CONTROL_PLANE_BASE_URL` is unset. There is no current gRPC contract between
`lotus-performance` and `lotus-core`.

Governed base-URL examples for the control-plane contract family are:

1. local ingress: `http://core-control.dev.lotus`
2. local host-port: `http://127.0.0.1:8202`
3. local Docker-to-host: `http://host.docker.internal:8202`
4. platform-stack internal: `http://lotus-core-control:8002`

## Upstream Client Surfaces

Implementation entrypoints:

1. `app/core/config.py`
2. `app/services/core_integration_service.py`
3. `app/services/stateful_input_service.py`
4. `app/services/portfolio_source_service.py`
5. `app/services/returns_series_service.py`
6. `app/services/stateful_benchmark_input_service.py`
7. `app/services/stateful_attribution_input_service.py`
8. `app/services/benchmark_exposure_context_service.py`

## Contract Family Mapping

| `lotus-performance` client method | Upstream `lotus-core` route | RFC-0082 family | Current usage |
| --- | --- | --- | --- |
| `get_portfolio_analytics_timeseries` | `POST /integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries` | Analytics input | Stateful TWR, MWR, contribution, attribution, returns-series sourcing |
| `get_position_analytics_timeseries` | `POST /integration/portfolios/{portfolio_id}/analytics/position-timeseries` | Analytics input | Stateful contribution and attribution position sourcing |
| `get_portfolio_analytics_reference` | `POST /integration/portfolios/{portfolio_id}/analytics/reference` | Analytics input | Portfolio open date, reporting currency, and reference metadata for performance workflows |
| `get_benchmark_assignment` | `POST /integration/portfolios/{portfolio_id}/benchmark-assignment` | Analytics input | Benchmark resolution for stateful benchmark-aware workflows |
| `get_benchmark_definition` | `POST /integration/benchmarks/{benchmark_id}/definition` | Analytics input watchlist | Benchmark metadata sourcing; should remain source-data only |
| `get_benchmark_composition_window` | `POST /integration/benchmarks/{benchmark_id}/composition-window` | Analytics input watchlist | Core-sourced benchmark composition windows for calculated benchmark performance |
| `get_benchmark_market_series` | `POST /integration/benchmarks/{benchmark_id}/market-series` | Analytics input watchlist | Component weights and index returns for benchmark exposure context and benchmark calculation |
| `get_benchmark_return_series` | `POST /integration/benchmarks/{benchmark_id}/return-series` | Analytics input | Explicit vendor-series benchmark return sourcing |
| `get_index_catalog` | `POST /integration/indices/catalog` | Analytics input watchlist | Index lookup for benchmark exposure context |
| `get_index_price_series` | `POST /integration/indices/{index_id}/price-series` | Analytics input watchlist | Component/index price sourcing for benchmark calculations |
| `get_risk_free_series` | `POST /integration/reference/risk-free-series` | Analytics input watchlist | Risk-free return/rate series for returns-series and benchmark-aware workflows |
| `get_fx_rates` | `GET /fx-rates/` | Operational read | FX rate lookup for multi-currency stateful benchmark and performance workflows |

## Consumer Conformance Rules

`lotus-performance` must keep these rules true:

1. performance analytics conclusions stay in `lotus-performance`;
2. `lotus-core` is consumed for canonical source data, reference data, and analytics inputs only;
3. upstream calls use the governed REST/OpenAPI contracts exposed by `lotus-core`;
4. stateful calls stamp or propagate consumer identity and correlation context where the route supports it;
5. large-window retrieval keeps paging, chunking, and retry behavior inside the consumer orchestration layer;
6. lineage stores upstream request and response fingerprints for reproducibility where a durable calculation is involved;
7. the watchlist routes above require explicit RFC-0082 review before their semantics are expanded.

Route-specific downstream interpretations that must stay truthful:

1. benchmark assignment resolution is keyed by `portfolio_id` and `as_of_date`; request
   `reporting_currency` is caller-context metadata and must not be treated as a benchmark-selection
   key unless lotus-core explicitly versions that behavior in the public contract;
2. `POST /integration/reference/risk-free-series` returning an empty `points` list means the route
   is reachable but usable source data is absent for the requested currency/window, so downstream
   consumers must treat that as a data-availability gap rather than a methodology signal to fall
   back to zero risk-free inputs;
3. `POST /integration/indices/catalog` classification labels, including canonical broad-market
   sector labels such as `broad_market_equity` and `broad_market_fixed_income`, are source-owned
   metadata; `lotus-performance` must not synthesize missing sector labels locally.

## Existing Conformance Evidence

Current test and implementation evidence:

1. `tests/unit/services/test_core_integration_service.py`
   Verifies client request shapes for core analytics-input and reference contracts.
2. `tests/unit/services/test_stateful_input_service.py`
   Verifies chunking, paging, upstream failure propagation, and snapshot recording behavior.
3. `tests/benchmarks/test_stateful_input_performance.py`
   Exercises stateful input retrieval performance characteristics.
4. `tests/integration/test_returns_series_api.py`
   Verifies stateful returns-series sourcing through core-backed inputs.
5. `tests/integration/test_benchmark_api.py`
   Verifies stateful benchmark sourcing, index series, FX, and benchmark return integration.
6. `tests/integration/test_attribution_api.py`
   Verifies stateful attribution sourcing through core-backed portfolio, position, and benchmark inputs.
7. `tests/integration/test_benchmark_exposure_context_api.py`
   Verifies benchmark exposure context sourcing from core-backed index and benchmark inputs.

## Current Gap Register

1. `GET /fx-rates/` is currently an operational read rather than an `/integration/reference/*`
   analytics-input contract. This is acceptable because it remains source-data retrieval, but any future
   analytics-specific FX semantics should be introduced as a governed analytics-input contract rather than
   expanding the operational read implicitly.
2. Benchmark, index, risk-free, taxonomy, and enrichment routes are RFC-0082 watchlist areas. They should
   not be broadened into performance conclusions or benchmark analytics that belong in `lotus-performance`.
3. Transport optimization is deferred. Retrieval performance work should first profile chunk size, page size,
   export behavior, concurrency, retry policy, and upstream database/query shape before proposing gRPC.
   Current Slice 4 evidence is recorded in `docs/technical/RFC-0082-retrieval-performance-hardening.md`.

## Validation Lane

This document is docs-only consumer-conformance hardening. Minimum validation is Feature Lane docs proof plus
targeted upstream-client test review.

Run code gates only when a future slice changes client behavior, request/response contracts, OpenAPI output,
or runtime coupling.
