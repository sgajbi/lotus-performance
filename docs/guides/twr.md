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

In stateful mode, lotus-performance retrieves portfolio timeseries from lotus-core query-control-plane
through `CORE_CONTROL_PLANE_BASE_URL`,
normalizes them into canonical valuation points, then runs the same owned TWR engine
used by stateless requests.

Preferred local defaults for `CORE_CONTROL_PLANE_BASE_URL` are:

- app/runtime: `http://core-control.dev.lotus`
- local host-port: `http://127.0.0.1:8202`
- Docker-to-host: `http://host.docker.internal:8202`
- platform-stack internal: `http://lotus-core-control:8002`

`CORE_QUERY_BASE_URL` remains a deprecated compatibility fallback only when
`CORE_CONTROL_PLANE_BASE_URL` is unset.

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

For stateful benchmark assignment, lotus-core currently resolves the assignment by
`portfolio_id + as_of_date`. Request context such as reporting currency is useful for lineage and
consumer symmetry, but should not be treated as changing assignment selection unless lotus-core
explicitly versions that behavior in the public contract.

When benchmark output is requested, TWR returns:

- a parallel `benchmark` block calculated through the shared benchmark engine
- per-period `relative_performance`

Every completed synchronous TWR response also returns `calculation_supportability`. This bounded
supportability block is the source-owned front-office posture for the calculation:

- `state`: `ready`, `stale`, `degraded`, `empty`, `error`, or `unsupported`
- `reason`: a bounded machine-readable reason such as `calculation_complete`,
  `stale_source_observations`, or `insufficient_valuation_points`
- `freshness_bucket`: `current`, `same_day`, `stale`, or `unknown`
- `input_row_count`, `resolved_period_count`, and `benchmark_row_count`
- `metric_labels`: the bounded Prometheus label keys emitted for supportability metrics

The same posture is exported through
`lotus_performance_calculation_supportability_total{operation="twr",supportability_state,reason,freshness_bucket}`.
It also increments the RFC-0108 backend freshness counter
`lotus_analytics_freshness_bucket_total{service="lotus-performance",operation="twr",freshness_bucket,supportability_state}`.
Labels are intentionally bounded and must not include portfolio, client, tenant, account, benchmark,
calculation, trace, correlation, request body, response body, or security identifiers. Tests assert
that the response contract and Prometheus exposition stay aligned.

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

Performance resets exist because geometric linking is only meaningful while the portfolio remains a
coherent invested path. When capital is effectively broken, liquidated, recapitalized, or pushed
through a collapse boundary, the engine prefers a reset to linking mathematically valid but
economically misleading returns.

See [performance-reset-scenarios.md](../technical/performance-reset-scenarios.md) for business
examples that explain when resets should and should not happen.

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

Daily portfolio breakdown entries include `calculation_evidence` as a curated, implementation-backed
explanation of the daily TWR calculation. This evidence is returned independently of raw
timeseries output and includes the calculation method, denominator basis, flow timing convention,
beginning and ending market value, beginning-of-day and end-of-day external flows, external inflows
and outflows, management fees, signed adjusted capital before denominator policy, adjusted capital,
performance P&L, daily return, calculation status, linkability status, episode status, reason codes,
and warnings.

The denominator basis is `absolute_begin_mv_plus_bod_cf`: Lotus uses the absolute value of
beginning market value plus beginning-of-day external cash flow as the invested capital denominator.
Beginning-of-day flows adjust invested capital. End-of-day flows are neutralized from performance
P&L but do not adjust the denominator.

`linkability_status` explains whether the day can participate in geometric linking. `linkable`
means the daily return can be compounded normally, `reset_boundary` means compounding is explicitly
broken by a reset day, `not_calculated` means the row has no governed capital basis or is a
no-investment/effective-period exclusion, and `not_linkable` means the daily return crossed a
full-loss boundary such as `-100%` or below. `episode_status` explains the row's TWR episode:
`open`, `reset_boundary`, `no_investment`, or `not_in_period`.

If `output.include_timeseries` is enabled, daily breakdown entries can also include raw `daily_data`.
Raw `daily_data` is drill-down material; `calculation_evidence` is the supported calculation
contract for explaining how the daily return was produced.

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
      "portfolio": {
        "summary": {
          "period_return": {
            "local": 3.0201,
            "fx": 0.0,
            "base": 3.0201
          },
          "cumulative_return": {
            "local": 3.0201,
            "fx": 0.0,
            "base": 3.0201
          }
        },
        "breakdowns": {
          "daily": [],
          "monthly": []
        }
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
