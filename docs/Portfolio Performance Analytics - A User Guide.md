# Portfolio Performance Analytics User Guide

This guide explains what `lotus-performance` does today and how to use the main analytics
surfaces without relying on outdated request examples.

## What the service answers

The current public APIs answer four distinct questions:

1. What was my portfolio return?
2. What contributed to that return?
3. Why did the portfolio differ from its benchmark?
4. What canonical return series should downstream analytics consume?

## 1. Measuring return

### Time-weighted return

Use `POST /performance/twr` when you want manager-skill style performance that neutralizes
external cash-flow timing.

Current request shape:

- `portfolio_id`
- `performance_start_date`
- `report_end_date`
- `analyses`
- `valuation_points`

Use TWR for:

- manager evaluation
- benchmark comparison
- period-by-period reporting

### Money-weighted return

Use `POST /performance/mwr` when you want the investor-experience return that reflects cash-flow
timing and size.

Current request shape:

- `portfolio_id`
- `begin_mv`
- `end_mv`
- `cash_flows`
- `as_of`
- `mwr_method`

Use MWR for:

- investor outcome reporting
- capital deployment analysis
- cash-flow-sensitive return measurement

## 2. Explaining return drivers

### Contribution

Use `POST /performance/contribution` to decompose portfolio return into position or hierarchy-level
drivers.

Contribution answers:

- which holdings added value
- which holdings detracted
- how groups such as sector or strategy rolled up into total return

Large contribution requests may run asynchronously. In that case the API returns `202 Accepted`
with:

- `calculation_id`
- `poll_path`
- `result_path`

### Attribution

Use `POST /performance/attribution` to explain active return versus a benchmark through allocation,
selection, and interaction effects.

Attribution answers:

- whether excess return came from allocation decisions
- whether security selection was beneficial
- how benchmark-relative effects reconciled to active return

Large attribution requests may also run asynchronously with the same `202 Accepted` pattern.

## 3. Canonical returns series for downstream consumers

Use `POST /integration/returns/series` when another analytics service needs a canonical portfolio,
benchmark, or risk-free return series.

This endpoint supports:

- `input_mode: "stateless"`
- `input_mode: "stateful"`

Stateful mode retrieves source data from lotus-core, records upstream retrieval snapshots durably,
and may offload longer windows to the compute executor.

## 4. Async execution and support flows

Executor-backed requests should be handled using the durable polling surfaces:

- lifecycle polling: `GET /performance/executions/{calculation_id}`
- contribution result retrieval: `GET /performance/contribution/results/{calculation_id}`
- attribution result retrieval: `GET /performance/attribution/results/{calculation_id}`
- returns-series result retrieval: `GET /integration/returns/series/results/{calculation_id}`
- lineage retrieval: `GET /performance/lineage/{calculation_id}`

For runtime support and backlog visibility:

- runtime status: `GET /integration/runtime-status`
- readiness: `GET /health/ready`
- metrics: `GET /metrics`

## 5. Reproducibility and auditability

Every calculation has a durable `calculation_id`. Responses and execution records also carry
reproducibility metadata such as canonical hashes and execution stages.

Lineage is handled asynchronously:

- the API stores lineage payload metadata durably
- the lineage worker materializes request, response, and detail artifacts
- clients retrieve artifact references through `/performance/lineage/{calculation_id}`
- artifact downloads are served through `/performance/lineage/{calculation_id}/artifacts/{artifact_name}`

See:

- [guides/reproducibility.md](guides/reproducibility.md)
- [guides/api_reference.md](guides/api_reference.md)

## 6. Where to get exact field-level contract detail

Use generated OpenAPI for exact field names, descriptions, enums, and examples:

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`

This user guide is intentionally conceptual. It should not be treated as the canonical field-by-field
schema reference.
