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

## Current request-model shape

### TWR

`POST /performance/twr` uses:

- `portfolio_id`
- `performance_start_date`
- `report_end_date`
- `analyses`
- `valuation_points`

The public request contract is analysis-based. Older examples using `period_type`,
`frequencies`, or `daily_data` are not current.

### MWR

`POST /performance/mwr` uses:

- `portfolio_id`
- `begin_mv`
- `end_mv`
- `cash_flows`
- `as_of`
- `mwr_method`

### Contribution

`POST /performance/contribution` uses:

- `portfolio_id`
- `report_start_date`
- `report_end_date`
- `analyses`
- `portfolio_data`
- `positions_data`

Large position sets can be executor-offloaded and return `202 Accepted`.

### Attribution

`POST /performance/attribution` uses:

- `portfolio_id`
- `report_start_date`
- `report_end_date`
- `analyses`
- `mode`
- `group_by`
- benchmark and portfolio input blocks

Large input sets can be executor-offloaded and return `202 Accepted`.

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
- stateful integration resolves lotus-core through `CORE_QUERY_BASE_URL`

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
