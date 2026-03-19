# Time-Weighted Return Guide

`POST /performance/twr` calculates time-weighted return across one or more requested analysis
periods and returns breakdowns by the requested reporting frequencies.

## Current request contract

`POST /performance/twr` now supports two request modes:

- `input_mode="stateless"`
- `input_mode="stateful"`

Common top-level fields are:

- `portfolio_id`
- `performance_start_date`
- `report_end_date`
- `analyses`
- optional `benchmark`

Stateless mode accepts either:

- legacy top-level `valuation_points`
- or `stateless_input.valuation_points`

Stateful mode uses:

- `stateful_input.consumer_system`

In stateful mode, lotus-performance retrieves portfolio timeseries from lotus-core,
normalizes them into canonical valuation points, then runs the same owned TWR engine
used by stateless requests.

Optional controls include:

- `report_start_date` for explicit-window analysis
- `annualization`
- `output`
- `reset_policy`
- `data_policy`
- multi-currency fields such as `currency_mode`, `report_ccy`, `fx`, and `hedging`

When `benchmark` is supplied, TWR returns a parallel benchmark block calculated through the shared
benchmark engine. Benchmark requests support the same benchmark modes as the dedicated benchmark
endpoint:

- `benchmark.input_mode="stateless" | "stateful"`
- `benchmark.return_source="calculated" | "vendor_series"`
- stateful benchmark mode can resolve benchmark assignment from lotus-core when `benchmark_id` is omitted

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

- `breakdowns`
- `portfolio_return`
- `reset_events`

If `output.include_timeseries` is enabled, daily breakdown entries can also include `daily_data`.

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
    { "day": 1, "perf_date": "2025-01-01", "begin_mv": 100000.0, "end_mv": 101000.0 },
    { "day": 2, "perf_date": "2025-01-02", "begin_mv": 101000.0, "end_mv": 102010.0 },
    { "day": 3, "perf_date": "2025-01-03", "begin_mv": 102010.0, "end_mv": 100989.9 },
    { "day": 4, "perf_date": "2025-01-04", "begin_mv": 100989.9, "bod_cf": 25000.0, "end_mv": 127249.29 },
    { "day": 5, "perf_date": "2025-01-05", "begin_mv": 127249.29, "end_mv": 125976.7971 }
  ]
}
```

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
  "performance_start_date": "2024-12-31",
  "report_end_date": "2025-01-31",
  "metric_basis": "NET",
  "analyses": [
    {
      "period": "YTD",
      "frequencies": ["daily", "monthly"]
    }
  ],
  "stateful_input": {
    "consumer_system": "lotus-performance"
  }
}
```

Use Swagger at `/docs` for exact field-level descriptions and current examples.
