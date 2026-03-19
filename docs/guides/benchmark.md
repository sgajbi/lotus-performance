# Benchmark Guide

`POST /performance/benchmark` calculates benchmark performance from either caller-supplied stateless
inputs or lotus-core-backed stateful sourcing.

## Current request contract

`POST /performance/benchmark` supports two request modes:

- `input_mode="stateless"`
- `input_mode="stateful"`

Common top-level fields are:

- `benchmark_id`
- `benchmark_start_date`
- `report_end_date`
- `analyses`
- `return_source`

Stateless mode uses:

- `stateless_input.benchmark_currency`
- `stateless_input.component_observations` when `return_source="calculated"`
- `stateless_input.benchmark_return_points` when `return_source="vendor_series"`

Stateful mode uses:

- `stateful_input.consumer_system`

In stateful mode, lotus-performance sources benchmark definition, component price series, and FX
rates from lotus-core, then normalizes those upstream inputs into canonical benchmark component
observations before running the owned benchmark engine.

## Return-source behavior

The public contract supports two explicit return-source modes:

- `return_source="calculated"`
- `return_source="vendor_series"`

Default behavior is `return_source="calculated"`.

In calculated mode:

- lotus-performance derives component daily returns
- lotus-performance computes daily component contributions
- lotus-performance sums component contributions into benchmark daily return
- lotus-performance geometrically links daily benchmark return into period return

In vendor-series mode:

- lotus-performance accepts or sources benchmark return points directly
- the response still uses the same benchmark period/result shape
- component contribution output is not emitted because the engine did not calculate the benchmark

## Current stateful fence

Calculated stateful benchmark mode currently requires the requested window to remain inside a
single effective lotus-core composition segment.

That means:

- benchmark definition must cover the request window with one effective component-weight schedule
- lotus-performance does not yet expand multi-rebalance benchmark composition windows internally

Vendor-series mode does not rely on component expansion and therefore does not carry that specific
fence.

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
  "stateful_input": {
    "consumer_system": "lotus-performance"
  }
}
```

Use Swagger at `/docs` for exact field-level descriptions and current examples.
