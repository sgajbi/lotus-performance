# Portfolio Performance Analytics API

`lotus-performance` is the analytics service in the Lotus platform. It owns:

- time-weighted return (`POST /performance/twr`)
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
- Reproducibility and lineage: [guides/reproducibility.md](docs/guides/reproducibility.md)

Async-capable endpoints follow one common pattern:

1. client submits the request
2. API returns a final response or `202 Accepted`
3. client polls `/performance/executions/{calculation_id}`
4. client retrieves the endpoint-specific async result from `result_path`

`calculation_id` is the durable execution handle for that workflow:

- exact async resubmission with the same `calculation_id` is treated as an idempotent replay
- payload drift with the same `calculation_id` is rejected with `409 Conflict`
- synchronous submissions should use a fresh `calculation_id` each time

## Current request-model shape

### TWR

`POST /performance/twr` uses:

- `input_mode: "stateless" | "stateful"`
- `portfolio_id`
- `performance_start_date`
- `report_end_date`
- `analyses`
- stateless:
  - `valuation_points` for legacy callers
  - or `stateless_input.valuation_points` for Lotus-style mode envelopes
- stateful:
  - `stateful_input.consumer_system`
  - lotus-core portfolio timeseries are normalized into canonical valuation points inside lotus-performance

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
  - `stateful_input.consumer_system`
  - `stateful_input.window_start_date`
  - lotus-core portfolio timeseries are normalized into canonical MWR inputs inside lotus-performance

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
  - `stateful_input.consumer_system`
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
  - `stateful_input.consumer_system`
  - optional `stateful_input.benchmark_id`
  - portfolio and position inputs sourced from lotus-core query-control-plane
  - current fences: `mode="by_instrument"` and `group_by` limited to `asset_class`, `sector`, `country`, `currency`
  - `currency_mode="BOTH"` is supported in stateful mode when `report_ccy` is present and `fx.rates` are supplied for mixed-currency sourced positions

Large input sets and long-window stateful attribution requests can be executor-offloaded and return `202 Accepted`.

### Returns series integration

`POST /integration/returns/series` supports:

- `input_mode: "stateless" | "stateful"`
- canonical portfolio return series
- optional benchmark and risk-free series
- sync or async execution depending on workload shape

## Setup

### Local Python environment

```bash
make install
make run
```

Swagger with local `make run` defaults:

- `http://127.0.0.1:8000/docs`

### Docker compose

```bash
docker compose up
```

Default host port in compose:

- `http://127.0.0.1:${PA_HOST_PORT:-8002}/docs`

Important compose defaults:

- API container listens on `8000`
- host port defaults to `8002`
- stateful integration resolves lotus-core query-control-plane through `CORE_QUERY_BASE_URL`
- local compose default for `CORE_QUERY_BASE_URL` is `http://host.docker.internal:8202`
- runtime threshold profile overrides can be layered with:
  - `docker compose -f docker-compose.yml -f docs/examples/docker-compose.runtime-thresholds.production.yml up`
- optional scheduled runtime-retention automation can be enabled with the ops profile:
  - `docker compose --profile ops up performance-runtime-retention-worker`

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
- [guides/multi_currency.md](docs/guides/multi_currency.md)
- [technical/methodology_index.md](docs/technical/methodology_index.md)
- [methodologies/metrics/master-index.md](docs/methodologies/metrics/master-index.md)
- [guides/standalone_engine_usage.md](docs/guides/standalone_engine_usage.md)
