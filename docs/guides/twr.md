# Time-Weighted Return Guide

`POST /performance/twr` calculates time-weighted return across one or more requested analysis
periods and returns breakdowns by the requested reporting frequencies.

## Current request contract

`POST /performance/twr` now supports two request modes:

- `input_mode="stateless"`
- `input_mode="stateful"`

Execution mode:

- synchronous for smaller requests
- `202 Accepted` when larger TWR workloads are offloaded to the compute executor
- async poll path: `/performance/executions/{calculation_id}`
- async result path: `/performance/twr/results/{calculation_id}`

Common top-level fields are:

- optional `calculation_id`
- `portfolio_id`
- `performance_start_date` in stateless mode
- `report_end_date`
- `analyses`
- optional `include_benchmark`
- optional `benchmark`

Stateless mode accepts either:

- legacy top-level `valuation_points`
- or `stateless_input.valuation_points`

Stateful mode uses:

- `stateful_input`

In stateful mode, lotus-performance retrieves portfolio timeseries from lotus-core,
normalizes them into canonical valuation points, then runs the same owned TWR engine
used by stateless requests.

The stateful envelope is intentionally lightweight. lotus-performance stamps the
source consumer identity server-side instead of requiring an explicit consumer field.

If `calculation_id` is omitted, lotus-performance generates one and returns it in the response.

Optional controls include:

- `report_start_date` for explicit-window analysis
- `annualization`
- `output`
- `reset_policy`
- `data_policy`
- multi-currency fields such as `currency_mode`, `report_ccy`, `fx`, and `hedging`

Use `include_benchmark=true` when benchmark performance should be returned alongside portfolio TWR.
The nested `benchmark` object is optional configuration, not the inclusion switch itself.

Benchmark selection follows this precedence:

1. `benchmark.benchmark_id` when supplied
2. lotus-core benchmark assignment in stateful mode
3. validation error if stateless mode requests benchmark output without a benchmark configuration

When benchmark output is requested, TWR returns:

- a parallel `benchmark` block calculated through the shared benchmark engine
- per-period `relative_performance`

Benchmark requests support the same benchmark modes as the dedicated benchmark endpoint:

- `benchmark.input_mode="stateless" | "stateful"`
- `benchmark.return_source="calculated" | "vendor_series"`
- stateless benchmark calculated mode accepts exactly one of:
  - `benchmark.stateless_input.component_observations`
  - `benchmark.stateless_input.component_price_points`
- stateful benchmark mode can resolve benchmark assignment from lotus-core when `benchmark_id` is omitted
- stateful benchmark mode can also run with `include_benchmark=true` and no nested `benchmark` block

Older examples using `period_type`, top-level `frequencies`, or `daily_data` are not current.

## Core methodology

### 1. Daily return

For each valuation point, the engine calculates a daily return that isolates investment performance
from beginning-of-day and end-of-day cash flows. Management fees affect the daily result when
`metric_basis="NET"`.

### 2. Geometric linking

Daily returns are geometrically linked across each requested analysis window to produce period-level
time-weighted return.

### 3. Long and short sleeve handling

The engine maintains separate long and short compounding paths so that sign flips and short exposure
are handled consistently instead of forcing all exposure through a single naive compounding stream.

### 4. Robustness rules

The engine applies:

- no-investment-period handling
- performance reset logic
- optional data-policy overrides, ignored days, and outlier flagging

### 5. Multi-period slicing

The API resolves each requested analysis in `analyses`, computes the master daily series once, then
slices and aggregates results by period and requested frequencies.

## Current response shape

The response contains:

- `calculation_id`
- `portfolio_id`
- `input_mode`
- `results_by_period`
- `meta`
- `diagnostics`
- `audit`

Each period result may contain:

- `portfolio`
- `benchmark`
- `relative_performance`
- `reset_events`

If `output.include_timeseries` is enabled, daily breakdown entries can also include `daily_data`.

When benchmark output is included, each period result uses sibling comparative blocks:

- `portfolio`
- `benchmark`
- `relative_performance`

The response also emits top-level `benchmark_context` when a benchmark was resolved, so callers do
not need to infer the benchmark identity from an individual period block.

Each block carries:

- `summary.period_return`
- `summary.cumulative_return`
- requested-frequency breakdown rows with `period_return` and `cumulative_return`

Portfolio and benchmark cumulative values are geometrically linked through the row end date.
Relative-performance cumulative values are arithmetic:

`cumulative_relative_return = cumulative_portfolio_return - cumulative_benchmark_return`

## Multi-currency behavior

When `currency_mode="BOTH"` and FX inputs are provided, the period-level `portfolio_return`
contains:

- `local`
- `fx`
- `base`

See [multi_currency.md](multi_currency.md) for the detailed multi-currency path.

## Example request

```json
{
  "input_mode": "stateless",
  "portfolio_id": "TWR_EXAMPLE_01",
  "performance_start_date": "2024-12-31",
  "report_end_date": "2025-01-05",
  "metric_basis": "NET",
  "analyses": [
    {
      "period": "YTD",
      "frequencies": ["daily", "monthly"]
    }
  ],
  "valuation_points": [
    { "perf_date": "2025-01-01", "begin_mv": 100000.0, "end_mv": 101000.0 },
    { "perf_date": "2025-01-02", "begin_mv": 101000.0, "end_mv": 102010.0 },
    { "perf_date": "2025-01-03", "begin_mv": 102010.0, "end_mv": 100989.9 },
    { "perf_date": "2025-01-04", "begin_mv": 100989.9, "bod_cf": 25000.0, "end_mv": 127249.29 },
    { "perf_date": "2025-01-05", "begin_mv": 127249.29, "end_mv": 125976.7971 }
  ]
}
```

Observation order is derived from sorted `perf_date`; callers do not send a separate `day` field.

## Example response excerpt

```json
{
  "calculation_id": "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e",
  "portfolio_id": "TWR_EXAMPLE_01",
  "input_mode": "stateless",
  "results_by_period": {
    "YTD": {
      "breakdowns": {
        "daily": [],
        "monthly": []
      },
      "portfolio_return": {
        "local": 0.0,
        "fx": 0.0,
        "base": 3.0201
      }
    }
  },
  "meta": {},
  "diagnostics": {},
  "audit": {}
}
```

## Example stateful request

```json
{
  "input_mode": "stateful",
  "portfolio_id": "DEMO_DPM_EUR_001",
  "report_end_date": "2025-01-31",
  "metric_basis": "NET",
  "analyses": [
    {
      "period": "YTD",
      "frequencies": ["daily", "monthly"]
    }
  ],
  "stateful_input": {}
}
```

Use Swagger at `/docs` for exact field-level descriptions and current examples.
