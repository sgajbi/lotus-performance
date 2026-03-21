# Contribution Guide

`POST /performance/contribution` decomposes portfolio return into position-level or hierarchy-level
contributors.

## Current request contract

The current request shape is:

- `input_mode: "stateless" | "stateful"`
- `portfolio_id`
- `report_start_date`
- `report_end_date`
- `analyses`
- stateless:
  - legacy top-level `portfolio_data`
  - legacy top-level `positions_data`
  - or `stateless_input.portfolio_data`
  - or `stateless_input.positions_data`
- stateful:
  - `stateful_input`
  - optional `stateful_input.metric_basis`
  - optional `stateful_input.dimensions`
  - optional `stateful_input.include_cash_flows`
  - optional `stateful_input.filters`

The stateful envelope is intentionally lightweight. lotus-performance stamps the
source consumer identity server-side instead of requiring an explicit consumer field.

Optional controls include:

- `hierarchy`
- `weighting_scheme`
- `smoothing`
- `emit`
- `lookthrough`
- multi-currency controls

Inside the current contract:

- stateless `portfolio_data` contains `metric_basis` and `valuation_points`
- each stateless entry in `positions_data` contains `position_id`, optional `meta`, and `valuation_points`
- stateful mode sources canonical portfolio and position timeseries from lotus-core and normalizes them into the same stateless engine inputs used by direct requests

Older examples using nested `daily_data` or request-level `period_type` are not current.

## Async execution

Contribution can run synchronously or asynchronously.

Stateful and stateless requests follow the same execution pattern. The endpoint stays synchronous
for smaller stateless sets and smaller stateful windows, and returns `202 Accepted` when the
workload is offloaded to the compute executor.

When the request is offloaded, the API returns `202 Accepted` with:

- `calculation_id`
- `poll_path`
- `result_path`

Use:

- `GET /performance/executions/{calculation_id}`
- `GET /performance/contribution/results/{calculation_id}`

## Core methodology

### 1. Position return and weight

For each position and day, the engine computes:

- position return
- position weight relative to the total portfolio under the selected weighting scheme

### 2. Single-period contribution

Daily raw contribution is the position weight multiplied by position return.

### 3. Multi-period linking

The default smoothing method is `CARINO`, which is used so that multi-period contribution results
reconcile to the total geometric portfolio return.

### 4. Hierarchical aggregation

When `hierarchy` is supplied, the engine aggregates bottom-up from the most granular rows to each
parent level so that every level reconciles to its parent and ultimately to total portfolio return.
This is still a per-period calculation: when `analyses` requests multiple resolved periods, the API
returns one hierarchy result under each `results_by_period.<period>` key.

### 5. Residual and event consistency

Residual handling and event treatment are aligned with the underlying portfolio return engine:

- no-investment periods do not create artificial contribution
- reset behavior remains consistent with portfolio-level return logic
- small residuals are tracked and distributed so the final result reconciles

## Current response shape

The response contains:

- `calculation_id`
- `portfolio_id`
- `results_by_period`
- `meta`
- `diagnostics`
- `audit`

Depending on the request, each period result can include:

- `position_contributions`
- `summary`
- `levels`
- `timeseries`
- `total_contribution`

When `hierarchy` is present:

- `summary.portfolio_contribution` is the hierarchy-mode top-line contribution for that resolved period
- `levels[]` contains the bottom-up rollup for that same resolved period
- multi-period requests return separate hierarchy summaries for `MTD`, `YTD`, `ITD`, and so on, when those periods resolve

## Example request

```json
{
  "portfolio_id": "CONTRIB_EXAMPLE_01",
  "report_start_date": "2025-01-01",
  "report_end_date": "2025-01-02",
  "analyses": [
    {
      "period": "ITD",
      "frequencies": ["daily"]
    }
  ],
  "hierarchy": ["sector", "position_id"],
  "portfolio_data": {
    "metric_basis": "NET",
    "valuation_points": [
      { "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1020 },
      { "perf_date": "2025-01-02", "begin_mv": 1020, "bod_cf": 50, "end_mv": 1080 }
    ]
  },
  "positions_data": [
    {
      "position_id": "Stock_A",
      "meta": { "sector": "Technology" },
      "valuation_points": [
        { "perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612 },
        { "perf_date": "2025-01-02", "begin_mv": 612, "bod_cf": 50, "end_mv": 670 }
      ]
    },
    {
      "position_id": "Stock_B",
      "meta": { "sector": "Healthcare" },
      "valuation_points": [
        { "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408 },
        { "perf_date": "2025-01-02", "begin_mv": 408, "end_mv": 410 }
      ]
    }
  ]
}
```

## Example response excerpt

```json
{
  "calculation_id": "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e",
  "portfolio_id": "CONTRIB_EXAMPLE_01",
  "results_by_period": {
    "ITD": {
      "summary": {
        "portfolio_contribution": 2.95327
      },
      "levels": []
    }
  },
  "meta": {},
  "diagnostics": {},
  "audit": {}
}
```

Use `/docs` for exact response schemas, enum values, and examples.
