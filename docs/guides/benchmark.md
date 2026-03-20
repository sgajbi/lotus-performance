# Benchmark Guide

`POST /performance/benchmark` calculates benchmark performance from either caller-supplied stateless
inputs or lotus-core-backed stateful sourcing.

## Current request contract

`POST /performance/benchmark` supports two request modes:

- `input_mode="stateless"`
- `input_mode="stateful"`

Execution mode:

- synchronous for stateless requests and smaller stateful windows
- `202 Accepted` for larger stateful benchmark requests offloaded to the compute executor
- async poll path: `/performance/executions/{calculation_id}`
- async result path: `/performance/benchmark/results/{calculation_id}`

Common top-level fields are:

- `benchmark_id`
- `benchmark_start_date`
- `report_end_date`
- `analyses`
- `return_source`

Stateless mode uses:

- `stateless_input.benchmark_currency`
- exactly one of:
  - `stateless_input.component_observations`
  - `stateless_input.component_price_points`
  when `return_source="calculated"`
- `stateless_input.benchmark_return_points` when `return_source="vendor_series"`

Stateful mode uses:

- `stateful_input`

In stateful mode, lotus-performance sources benchmark definition, component price series, and FX
rates from lotus-core, then normalizes those upstream inputs into canonical benchmark component
observations before running the owned benchmark engine.

The stateful envelope is intentionally lightweight. lotus-performance stamps the
source consumer identity server-side instead of requiring an explicit consumer field.

## Return-source behavior

The public contract supports two explicit return-source modes:

- `return_source="calculated"`
- `return_source="vendor_series"`

Default behavior is `return_source="calculated"`.

In calculated mode:

- lotus-performance derives component daily returns
- stateless callers may provide either precomputed component returns or raw component price points
- when raw price points are supplied, lotus-performance derives component daily returns before contribution math
- lotus-performance computes daily component contributions
- lotus-performance sums component contributions into benchmark daily return
- lotus-performance geometrically links daily benchmark return into period return

In vendor-series mode:

- lotus-performance accepts or sources benchmark return points directly
- the response still uses the same benchmark period/result shape
- component contribution output is not emitted because the engine did not calculate the benchmark

## Stateful calculated sourcing

Calculated stateful benchmark mode now sources overlapping effective-dated benchmark composition
segments from lotus-core and applies beginning-of-day weights across rebalance windows.

That means:

- lotus-performance handles multi-segment benchmark composition windows internally
- benchmark weights remain beginning-of-day effective on each benchmark return date
- vendor-series mode still bypasses component expansion and uses sourced benchmark return points

## Core methodology

### 1. Daily component return

For each component and date, the benchmark engine calculates daily component return in benchmark
currency.

If the sourced component price series is not already in benchmark currency, lotus-performance
normalizes price levels using FX rates before deriving return.

### 2. Daily component contribution

Each component contribution is:

`weight_bop * component_return`

Weight application is beginning-of-day effective.

### 3. Daily benchmark return

Daily benchmark return is the sum of all daily component contributions.

### 4. Period benchmark return

Period benchmark return is the geometric link of daily benchmark return across the requested
window.

## Current response shape

The response contains:

- `calculation_id`
- `benchmark_id`
- `benchmark_currency`
- `input_mode`
- `return_source`
- `results_by_period`
- `meta`
- `diagnostics`
- `audit`

Each period result can include:

- `benchmark_return`
- `daily_returns`
- `component_contributions`

When `output.include_timeseries=true`, daily benchmark returns and per-component contribution rows
are emitted for calculated mode.

## Example stateless request

```json
{
  "input_mode": "stateless",
  "benchmark_id": "BMK_STATELESS_1",
  "benchmark_start_date": "2026-01-02",
  "report_end_date": "2026-01-03",
  "analyses": [
    {
      "period": "ITD",
      "frequencies": ["daily"]
    }
  ],
  "return_source": "calculated",
  "output": {
    "include_timeseries": true
  },
  "stateless_input": {
    "benchmark_currency": "USD",
    "component_observations": [
      {
        "component_id": "IDX_A",
        "date": "2026-01-02",
        "weight_bop": 0.6,
        "component_return": 0.02
      },
      {
        "component_id": "IDX_B",
        "date": "2026-01-02",
        "weight_bop": 0.4,
        "component_return": 0.01
      }
    ]
  }
}
```

## Example stateful request

```json
{
  "input_mode": "stateful",
  "benchmark_id": "BMK_STATEFUL_1",
  "benchmark_start_date": "2026-01-02",
  "report_end_date": "2026-01-03",
  "analyses": [
    {
      "period": "ITD",
      "frequencies": ["daily"]
    }
  ],
  "return_source": "calculated",
  "stateful_input": {}
}
```

Use Swagger at `/docs` for exact field-level descriptions and current examples.
