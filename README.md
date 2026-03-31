# Portfolio Performance Analytics API

`lotus-performance` is the analytics service in the Lotus platform. It owns:

- time-weighted return (`POST /performance/twr`)
- benchmark performance (`POST /performance/benchmark`)
- money-weighted return (`POST /performance/mwr`)
- contribution (`POST /performance/contribution`)
- attribution (`POST /performance/attribution`)
- canonical returns-series integration (`POST /integration/returns/series`)

It also owns durable execution lifecycle tracking, async compute offload for heavier workloads,
lineage artifact capture, and execution/result polling surfaces.

## Runtime model

The current runtime is a four-service topology:

1. `performance-analytics`
2. `performance-compute-executor`
3. `performance-lineage-worker`
4. `performance-lineage-db`

Source-of-truth runtime docs:

- [technical/architecture.md](docs/technical/architecture.md)
- [technical/runtime_topology.md](docs/technical/runtime_topology.md)

## Key contracts

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`
- Human API map: [guides/api_reference.md](docs/guides/api_reference.md)
- Complete service reference: [guides/complete_service_reference.md](docs/guides/complete_service_reference.md)
- Reproducibility and lineage: [guides/reproducibility.md](docs/guides/reproducibility.md)

Async-capable endpoints follow one common pattern:

1. client submits the request
2. API returns a final response or `202 Accepted`
3. client polls `/performance/executions/{calculation_id}`
4. client retrieves the endpoint-specific async result from `result_path`

Current endpoint-specific async result routes include:

- `/performance/twr/results/{calculation_id}`
- `/performance/benchmark/results/{calculation_id}`
- `/integration/returns/series/results/{calculation_id}`
- `/performance/contribution/results/{calculation_id}`
- `/performance/attribution/results/{calculation_id}`

`calculation_id` is the durable execution handle for that workflow:

- caller may omit `calculation_id`; lotus-performance generates one and returns it in the response
- exact async resubmission with the same `calculation_id` is treated as an idempotent replay
- payload drift with the same `calculation_id` is rejected with `409 Conflict`
- synchronous submissions should use a fresh `calculation_id` each time
- if omitted, lotus-performance generates one and returns it in the response

## Current request-model shape

### TWR

`POST /performance/twr` uses:

- `input_mode: "stateless" | "stateful"`
- `portfolio_id`
- `performance_start_date` in stateless mode
- `report_end_date`
- `analyses`
- `include_benchmark`
- stateless:
  - `valuation_points` for legacy callers
  - or `stateless_input.valuation_points` for Lotus-style mode envelopes
- stateful:
  - `stateful_input` is an empty Lotus envelope today
  - lotus-performance stamps source consumer identity server-side
  - lotus-core portfolio timeseries are normalized into canonical valuation points inside lotus-performance
- execution:
  - synchronous for smaller requests
  - `202 Accepted` when larger TWR workloads are offloaded to the compute executor
  - async result path: `/performance/twr/results/{calculation_id}`
- benchmark inclusion:
  - `include_benchmark=true` is the canonical switch for returning benchmark results alongside portfolio TWR
  - the nested `benchmark` object is optional configuration
  - explicit `benchmark.benchmark_id` overrides lotus-core assignment lookup
  - stateful mode can source the portfolio-to-benchmark mapping from lotus-core when `include_benchmark=true`
  - per-period responses include arithmetic `relative_performance`
  - responses also emit top-level `benchmark_context` when a benchmark was resolved

The public request contract is analysis-based. Older examples using `period_type`,
`frequencies`, or `daily_data` are not current.

### MWR

`POST /performance/mwr` uses:

- `input_mode: "stateless" | "stateful"`
- `portfolio_id`
- `as_of`
- `mwr_method`
- stateless:
  - legacy top-level `begin_mv`, `end_mv`, and `cash_flows`
  - or `stateless_input.begin_mv`, `stateless_input.end_mv`, and `stateless_input.cash_flows`
- stateful:
  - `stateful_input.window_start_date`
  - lotus-performance stamps source consumer identity server-side
  - lotus-core portfolio timeseries are normalized into canonical MWR inputs inside lotus-performance

### Benchmark

`POST /performance/benchmark` uses:

- `input_mode: "stateless" | "stateful"`
- `benchmark_id`
- `benchmark_start_date`
- `report_end_date`
- `analyses`
- `return_source: "calculated" | "vendor_series"`
- stateless:
  - `stateless_input.benchmark_currency`
  - exactly one of:
    - `stateless_input.component_observations`
    - `stateless_input.component_price_points`
    for calculated mode
  - `stateless_input.benchmark_return_points` for vendor-series mode
- stateful:
  - `stateful_input` is an empty Lotus envelope today
  - lotus-performance stamps source consumer identity server-side
  - benchmark definition, component price series, and FX inputs sourced from lotus-core
  - calculated mode supports multi-segment rebalance windows through the lotus-core composition-window contract

### Contribution

`POST /performance/contribution` uses:

- `input_mode: "stateless" | "stateful"`
- `portfolio_id`
- `report_start_date`
- `report_end_date`
- `analyses`
- stateless:
  - legacy top-level `portfolio_data` and `positions_data`
  - or `stateless_input.portfolio_data` and `stateless_input.positions_data`
- stateful:
  - `stateful_input` is the Lotus stateful envelope
  - lotus-performance stamps source consumer identity server-side
  - optional `stateful_input.metric_basis`
  - optional `stateful_input.dimensions`
  - optional `stateful_input.include_cash_flows`
  - optional `stateful_input.filters`
  - lotus-core portfolio and position timeseries are normalized into canonical contribution inputs inside lotus-performance

Large position sets and long-window stateful contribution requests can be executor-offloaded and return `202 Accepted`.

### Attribution

`POST /performance/attribution` uses:

- `portfolio_id`
- `report_start_date`
- `report_end_date`
- `analyses`
- `input_mode: "stateless" | "stateful"`
- `mode`
- `group_by`
- stateless:
  - benchmark and portfolio input blocks
- stateful:
  - `stateful_input` is the Lotus stateful envelope
  - lotus-performance stamps source consumer identity server-side
  - optional `stateful_input.benchmark_id`
  - portfolio and position inputs sourced from lotus-core query-control-plane
  - current fences: `mode="by_instrument"` and `group_by` limited to `asset_class`, `sector`, `country`, `currency`
  - `currency_mode="BOTH"` is supported in stateful mode when `report_ccy` is present and `fx.rates` are supplied for mixed-currency sourced positions
  - when a benchmark is resolved, the response also emits top-level `benchmark_context`

Large input sets and long-window stateful attribution requests can be executor-offloaded and return `202 Accepted`.

### Returns series integration

`POST /integration/returns/series` supports:

- `input_mode: "stateless" | "stateful"`
- canonical portfolio return series
- optional benchmark and risk-free series
- optional arithmetic `active_returns` series when both portfolio and benchmark returns are available
- cumulative return ladders:
  - `cumulative_portfolio_returns`
  - `cumulative_benchmark_returns`
  - `cumulative_risk_free_returns`
  - `cumulative_active_returns`
- when stateful benchmark resolution is used, the response also emits `benchmark_context`
- stateful benchmark sourcing now defaults to lotus-performance benchmark calculation
- stateful input uses a lightweight `stateful_input` envelope and stamps source consumer identity server-side
- `benchmark.return_source="vendor_series"` is an explicit stateful-only override for lotus-core benchmark return-series retrieval
- sync or async execution depending on workload shape

## Setup

### Local Python environment

```bash
make install
make run
```

Canonical local service identity:

- `http://performance.dev.lotus/docs`

Direct process bind details are implementation-only and should only matter when debugging the service in isolation.

### Docker compose

```bash
docker compose up
```

Canonical local compose access:

- `http://performance.dev.lotus/docs`

Important compose defaults:

- API container listens on `8000` internally
- local platform access should still use the canonical ingress identity above
- stateful integration resolves lotus-core query-control-plane through `CORE_QUERY_BASE_URL`
- RFC-0071 local ingress default for `CORE_QUERY_BASE_URL` is `http://core-query.dev.lotus`
- runtime threshold profile overrides can be layered with:
  - `docker compose -f docker-compose.yml -f docs/examples/docker-compose.runtime-thresholds.production.yml up`
- optional scheduled runtime-retention automation can be enabled with the ops profile:
  - `docker compose --profile ops up performance-runtime-retention-worker`

When running under the shared Lotus platform stack, prefer the platform-owned ingress and hostname mapping workflow documented in `lotus-platform/platform-stack/README.md` and `lotus-platform/Local Development Runbook.md`.

## Validation

Fast local gate:

```bash
make check
```

CI-shaped local gate:

```bash
make ci-local
```

Full test and coverage gate:

```bash
make test-all
```

## Documentation map

- [guides/twr.md](docs/guides/twr.md)
- [guides/mwr.md](docs/guides/mwr.md)
- [guides/contribution.md](docs/guides/contribution.md)
- [guides/attribution.md](docs/guides/attribution.md)
- [guides/complete_service_reference.md](docs/guides/complete_service_reference.md)
- [guides/workspace_summary.md](docs/guides/workspace_summary.md)
- [guides/multi_currency.md](docs/guides/multi_currency.md)
- [technical/methodology_index.md](docs/technical/methodology_index.md)
- [methodologies/metrics/master-index.md](docs/methodologies/metrics/master-index.md)
- [guides/standalone_engine_usage.md](docs/guides/standalone_engine_usage.md)
