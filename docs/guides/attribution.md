# Attribution Guide

`POST /performance/attribution` decomposes active return versus a benchmark into allocation,
selection, and interaction effects.

## Current request contract

The current request shape is:

- `input_mode: "stateless" | "stateful"`
- `portfolio_id`
- `report_start_date`
- `report_end_date`
- `analyses`
- `mode`
- `group_by`

Stateless callers provide:

- `benchmark_groups_data`
- `portfolio_data` plus `instruments_data` for `mode="by_instrument"`
- `portfolio_groups_data` for `mode="by_group"`

Stateful callers provide:

- `stateful_input.consumer_system`
- optional `stateful_input.metric_basis`
- optional `stateful_input.benchmark_id`
- optional `stateful_input.dimensions`
- optional `stateful_input.include_cash_flows`
- optional `stateful_input.filters`

In stateful mode, lotus-performance sources portfolio and position timeseries from lotus-core,
resolves benchmark assignment when needed, retrieves benchmark market-series metadata, and
normalizes those upstream inputs into the same stateless engine request used by direct callers.

The current stateful public contract is intentionally fenced to:

- `mode="by_instrument"`
- `currency_mode="BASE_ONLY"`
- `group_by` limited to `asset_class`, `sector`, or `country`

Optional controls include:

- `model`
- `linking`
- `frequency`
- multi-currency fields such as `currency_mode`, `report_ccy`, and `fx`

Older examples using request-level `period_type`, nested `daily_data`, or mixed camelCase group
dimensions are not current.

## Async execution

Attribution can run synchronously or asynchronously depending on workload shape.

The endpoint stays synchronous for smaller stateless sets and smaller stateful windows, and returns
`202 Accepted` when the request is offloaded to the compute executor.

When the request is offloaded, the API returns `202 Accepted` with:

- `calculation_id`
- `poll_path`
- `result_path`

Use:

- `GET /performance/executions/{calculation_id}`
- `GET /performance/attribution/results/{calculation_id}`

## Core methodology

### 1. Single-period effects

For each requested group, the engine computes active effects under the selected model:

- allocation
- selection
- interaction

The current public contract supports Brinson-style attribution models.

### 2. Multi-period linking

The engine links single-period effects over the requested analysis horizon using the selected
linking method so that aggregated effects reconcile against active return over time.

### 3. Grouping modes

`mode="by_instrument"`:

- instrument-level portfolio data is supplied
- the service aggregates to the requested grouping dimensions before attribution

`mode="by_group"`:

- callers provide already-grouped portfolio series directly

### 4. Hierarchical analysis

When `group_by` contains multiple dimensions, the engine produces multi-level attribution output so
that higher-level effects reconcile with the rollup of lower-level group effects.

### 5. Currency-aware attribution

When the multi-currency path is enabled, benchmark and portfolio observations can carry:

- `return_local`
- `return_fx`
- `return_base`

This allows the service to produce currency-aware active decomposition in addition to standard
base-return attribution.

Currency attribution is emitted only when all of these are true:

- `currency_mode="BOTH"`
- the aligned attribution panel contains the required local and FX return columns
- `group_by` includes the `currency` dimension so the engine can aggregate by currency

That path is currently available only for stateless attribution inputs. Stateful attribution is
currently fenced to `currency_mode="BASE_ONLY"` until lotus-core exposes the upstream benchmark
contracts needed for local and FX attribution inputs.

## Current response shape

The response contains:

- `calculation_id`
- `portfolio_id`
- `input_mode`
- `model`
- `linking`
- `results_by_period`
- `meta`
- `diagnostics`
- `audit`

Each period result can include:

- `levels`
- `reconciliation`
- `currency_attribution` when the multi-currency attribution path is active

## Example request

```json
{
  "portfolio_id": "ATTRIB_EXAMPLE_01",
  "mode": "by_instrument",
  "group_by": ["sector"],
  "linking": "none",
  "frequency": "daily",
  "report_start_date": "2025-01-01",
  "report_end_date": "2025-01-01",
  "analyses": [
    {
      "period": "ITD",
      "frequencies": ["daily"]
    }
  ],
  "portfolio_data": {
    "metric_basis": "NET",
    "valuation_points": [
      { "day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1018.5 }
    ]
  },
  "instruments_data": [
    {
      "instrument_id": "AAPL",
      "meta": { "sector": "Tech" },
      "valuation_points": [
        { "day": 1, "perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612 }
      ]
    },
    {
      "instrument_id": "JNJ",
      "meta": { "sector": "Health" },
      "valuation_points": [
        { "day": 1, "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 406.5 }
      ]
    }
  ],
  "benchmark_groups_data": [
    {
      "key": { "sector": "Tech" },
      "observations": [
        { "date": "2025-01-01", "return_base": 0.015, "weight_bop": 0.5 }
      ]
    },
    {
      "key": { "sector": "Health" },
      "observations": [
        { "date": "2025-01-01", "return_base": 0.02, "weight_bop": 0.5 }
      ]
    }
  ]
}
```

## Example response excerpt

```json
{
  "calculation_id": "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e",
  "portfolio_id": "ATTRIB_EXAMPLE_01",
  "model": "BF",
  "linking": "none",
  "results_by_period": {
    "ITD": {
      "levels": [],
      "reconciliation": {
        "total_active_return": 0.1
      }
    }
  },
  "meta": {},
  "diagnostics": {},
  "audit": {}
}
```

Use `/docs` for exact field-level descriptions and the latest examples.
