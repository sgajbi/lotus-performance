# Portfolio Performance Analytics API

`lotus-performance` is the analytics service in the Lotus platform. It owns:

- repository-local engineering context: `REPOSITORY-ENGINEERING-CONTEXT.md`

- time-weighted return (`POST /performance/twr`)
- benchmark performance (`POST /performance/benchmark`)
- money-weighted return (`POST /performance/mwr`)
- front-office workspace summary (`POST /performance/workspace-summary`)
- contribution (`POST /performance/contribution`)
- attribution (`POST /performance/attribution`)
- canonical returns-series integration (`POST /integration/returns/series`)
- benchmark exposure context (`POST /integration/benchmarks/exposure-context`)

It also owns durable execution lifecycle tracking, async compute offload for heavier workloads,
lineage artifact capture, TWR inspection/supportability triage, and execution/result polling surfaces.

## Runtime model

The current runtime is a four-service topology:

1. `performance-analytics`
2. `performance-compute-executor`
3. `performance-lineage-worker`
4. `performance-lineage-db`

Source-of-truth runtime docs:

- [technical/architecture.md](docs/technical/architecture.md)
- [technical/runtime_topology.md](docs/technical/runtime_topology.md)
- [technical/RFC-0082-upstream-contract-family-map.md](docs/technical/RFC-0082-upstream-contract-family-map.md)
- [technical/RFC-0082-retrieval-performance-hardening.md](docs/technical/RFC-0082-retrieval-performance-hardening.md)
- [technical/execution-polling-endpoint-certification.md](docs/technical/execution-polling-endpoint-certification.md)
- [technical/integration-capabilities-endpoint-certification.md](docs/technical/integration-capabilities-endpoint-certification.md)
- [technical/lineage-endpoint-certification.md](docs/technical/lineage-endpoint-certification.md)
- [technical/platform-surfaces-endpoint-certification.md](docs/technical/platform-surfaces-endpoint-certification.md)
- [technical/recovery-drills-endpoint-certification.md](docs/technical/recovery-drills-endpoint-certification.md)
- [technical/runtime-recoveries-endpoint-certification.md](docs/technical/runtime-recoveries-endpoint-certification.md)
- [technical/runtime-retention-endpoint-certification.md](docs/technical/runtime-retention-endpoint-certification.md)
- [technical/runtime-status-endpoint-certification.md](docs/technical/runtime-status-endpoint-certification.md)
- [technical/runtime-work-items-endpoint-certification.md](docs/technical/runtime-work-items-endpoint-certification.md)
- [technical/twr-inspection-endpoint-certification.md](docs/technical/twr-inspection-endpoint-certification.md)

Canonical stateful TWR inspection can be validated locally with:

```bash
python scripts/validate_canonical_twr_inspection.py \
  --performance-base-url http://127.0.0.1:8002 \
  --core-control-plane-base-url http://127.0.0.1:8202
```

This probes the lotus-core query-control-plane analytics-input POST routes, runs stateful TWR for
`PB_SG_GLOBAL_BAL_001` as of `2026-04-10`, and verifies the RFC-045 inspection evidence has no
source-economics or reconciliation regressions.

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
- `/performance/inspections/{inspection_id}`
- `/performance/benchmark/results/{calculation_id}`
- `/performance/workspace-summary/results/{calculation_id}`
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
  - lotus-core query-control-plane portfolio timeseries are normalized into canonical MWR inputs inside lotus-performance
  - explicit external cash flows and cross-observation capital carry-forward adjustments are included
    in the MWR cash-flow schedule
  - operational fees remain performance drag and are not treated as investor deposits or withdrawals

Use MWR when the business question is the client's capital-timing return. Use TWR when the question
is manager or strategy performance independent of deposits and withdrawals.

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

See [Benchmark Endpoint Certification](docs/technical/benchmark-endpoint-certification.md).

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
Contribution output is certified to keep period totals, position rows, optional daily series, optional
by-position series, and optional hierarchy levels reconciled to the same period contribution figure.
See [Contribution Endpoint Certification](docs/technical/contribution-endpoint-certification.md).

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
Attribution level outputs expose authoritative totals as both a nested `totals` block and explicit
`allocation_total_pct`, `selection_total_pct`, `interaction_total_pct`, and `total_effect_pct`
fields. Downstream systems should use those level totals for footers and summary-only views rather
than summing the currently visible group rows.
See [Attribution Endpoint Certification](docs/technical/attribution-endpoint-certification.md).

### Workspace summary

`POST /performance/workspace-summary` is the strategic, interaction-efficient surface for
front-office performance workspaces that need multi-horizon TWR, benchmark, active, and MWR summary
blocks in one coherent response. It is certified as a bounded summary endpoint, not a replacement
for contribution or attribution drill-downs.

New stateless callers should use `stateless_input.valuation_points`; the top-level
`valuation_points` field remains deprecated compatibility input. See
[Workspace Summary Endpoint Certification](docs/technical/workspace-summary-endpoint-certification.md).

### Benchmark exposure context

`POST /integration/benchmarks/exposure-context` serves the performance-aligned benchmark exposure
history used by `lotus-risk` stateful active-risk attribution. It is a derived lineage-backed view:
lotus-core remains the benchmark composition and classification system of record, while
lotus-performance keeps benchmark exposure history aligned with benchmark return context.

The v1 contract supports `POSITION`, `SECTOR`, and `ASSET_CLASS` grouping dimensions at
`frequency=DAILY`; `ISSUER` remains gated until issuer benchmark exposure semantics are approved.
See
[Benchmark Exposure Context Endpoint Certification](docs/technical/benchmark-exposure-context-endpoint-certification.md).

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

`series.*_returns` values are decimal ratios, not percentages. `active_returns` are pointwise
portfolio-minus-benchmark excess returns, while `cumulative_active_returns` is cumulative portfolio
return minus cumulative benchmark return. Stateful risk-free points that arrive from core as
annualized rates are normalized into period returns before response emission. Daily BUSINESS and
MARKET calendar policies filter output to weekdays before coverage diagnostics. See
[Returns-Series Endpoint Certification](docs/technical/returns-series-endpoint-certification.md).

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
- stateful integration resolves lotus-core query-control-plane through `CORE_CONTROL_PLANE_BASE_URL`
- current local ingress default for `CORE_CONTROL_PLANE_BASE_URL` is `http://core-control.dev.lotus`
- local host-port base URL for `CORE_CONTROL_PLANE_BASE_URL` is `http://127.0.0.1:8202`
- Docker-to-host base URL for `CORE_CONTROL_PLANE_BASE_URL` is `http://host.docker.internal:8202`
- platform-stack internal default for `CORE_CONTROL_PLANE_BASE_URL` is `http://lotus-core-control:8002`
- `CORE_QUERY_BASE_URL` remains a deprecated compatibility fallback when `CORE_CONTROL_PLANE_BASE_URL` is unset
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

PR-merge local gate:

```bash
make ci
```

Docker-parity local gate:

```bash
make ci-local
```

Full test, benchmark, and characterization gate:

```bash
make test-all
```

## Documentation map

- [guides/twr.md](docs/guides/twr.md)
- [technical/twr-endpoint-certification.md](docs/technical/twr-endpoint-certification.md)
- [guides/mwr.md](docs/guides/mwr.md)
- [technical/mwr-endpoint-certification.md](docs/technical/mwr-endpoint-certification.md)
- [technical/twr-mwr-response-attribute-certification.md](docs/technical/twr-mwr-response-attribute-certification.md)
- [guides/benchmark.md](docs/guides/benchmark.md)
- [technical/benchmark-endpoint-certification.md](docs/technical/benchmark-endpoint-certification.md)
- [guides/contribution.md](docs/guides/contribution.md)
- [guides/attribution.md](docs/guides/attribution.md)
- [guides/complete_service_reference.md](docs/guides/complete_service_reference.md)
- [guides/workspace_summary.md](docs/guides/workspace_summary.md)
- [guides/multi_currency.md](docs/guides/multi_currency.md)
- [technical/methodology_index.md](docs/technical/methodology_index.md)
- [methodologies/metrics/master-index.md](docs/methodologies/metrics/master-index.md)
- [guides/standalone_engine_usage.md](docs/guides/standalone_engine_usage.md)
