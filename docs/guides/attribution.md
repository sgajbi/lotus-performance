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

- `stateful_input`
- optional `stateful_input.metric_basis`
- optional `stateful_input.benchmark_id`
- optional `stateful_input.dimensions`
- optional `stateful_input.include_cash_flows`
- optional `stateful_input.filters`

The stateful envelope is intentionally lightweight. lotus-performance stamps the
source consumer identity server-side instead of requiring an explicit consumer field.

In stateful mode, lotus-performance sources portfolio and position timeseries from lotus-core,
resolves benchmark assignment when needed, resolves benchmark component inputs through the shared
benchmark engine sourcing path, and normalizes those upstream inputs into the same stateless engine
request used by direct callers.

Stateful position rows preserve the source position grain through `source_position_key`. When
lotus-core supplies account, custody, book, sleeve, strategy, mandate, or tax-lot discriminators,
Lotus treats those rows as distinct attribution instruments while preserving the original
`position_id` as `business_position_id` metadata.

The current stateful public contract is intentionally fenced to:

- `mode="by_instrument"`
- `group_by` limited to `asset_class`, `sector`, `country`, or `currency`
- `currency_mode="BOTH"` requires `report_ccy`
- `currency_mode="BOTH"` requires source position currencies and compares them to `report_ccy`
  after trimming and uppercasing currency codes
- `currency_mode="BOTH"` requires `fx.rates` when sourced positions include currencies different from `report_ccy`

For cross-endpoint currency vocabulary, use the
[RFC-020 multi-currency support matrix](../technical/rfc-020-multi-currency-support-matrix.md).

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

That path is available for both stateless and stateful attribution inputs. In stateful mode,
lotus-performance sources benchmark components from lotus-core, calculates benchmark returns
internally, and decomposes portfolio and benchmark returns into local and FX effects inside the
attribution engine.

## Current response shape

The response contains:

- `calculation_id`
- `portfolio_id`
- `input_mode`
- `benchmark_context` when a benchmark was resolved in stateful mode
- `model`
- `linking`
- `results_by_period`
- `meta`
- `diagnostics`
- `audit`

Completed attribution responses always include the same shared footer family used by TWR, MWR, and
Contribution. The attribution `diagnostics` block includes period-status counts, residual
materiality counts, supportability-evidence counts, and source-limit notes when upstream contracts
do not yet expose benchmark version, classification version, calendar policy, derivative flags,
or short flags. The attribution `audit.counts` block includes bounded input, portfolio,
benchmark, period, level, group, reason, supportability-issue, residual-materiality, and benchmark
context counts.

Each period result can include:

- `status`
- `reason_codes`
- `reasons`
- `levels`
- `reconciliation`
- `supportability_evidence`
- `currency_attribution` when the multi-currency attribution path is active
- `currency_attribution_totals` when the multi-currency attribution path is active

Use `status`, `reason_codes`, `reasons`, and `supportability_evidence` as the authoritative
front-office degraded-state contract for a period. A period can be mathematically calculated but
still be `partial` when there is off-benchmark exposure, benchmark-only exposure, unclassified
segments, missing benchmark evidence, skipped linking, an invalid multi-period return chain,
currency-attribution gaps, including absent currency grouping or missing local/FX evidence, or a
material residual. `reconciliation.residual_materiality` classifies
the active-return residual against the governed warning and material thresholds. When linked
attribution is requested and any portfolio or benchmark period return is less than or equal to
`-100%`, `supportability_evidence.linking_status` is `invalid_return_chain` and
`reason_codes` includes `linking_invalid_return_chain`; single-period evidence remains available,
but the linked period should not be used as a clean smoothed attribution view.

When currency attribution is active, `currency_attribution[]` contains the per-currency
Karnosky-Singer breakdown and `currency_attribution_totals` contains the portfolio-level total
across all emitted currency buckets. Downstream consumers should use `currency_attribution_totals`
for portfolio-level FX attribution displays, report inputs, and reconciliation checks instead of
summing visible currency rows.

Each `levels[].groups[]` row now carries side-by-side front-office context in addition to the
effect terms:

- `portfolio_weight_avg`: average portfolio weight in percentage units
- `benchmark_weight_avg`: average benchmark weight in percentage units
- `portfolio_return`: linked group portfolio return in percentage-point output units
- `benchmark_return`: linked group benchmark return in percentage-point output units
- `allocation`
- `selection`
- `interaction`
- `total_effect`

This lets downstream analytical surfaces show the standard portfolio-versus-benchmark view without
reverse-engineering group economics from the effect totals alone.

Each `levels[]` object also carries authoritative level totals:

- `totals.allocation`, `totals.selection`, `totals.interaction`, and `totals.total_effect`
- `allocation_total_pct`
- `selection_total_pct`
- `interaction_total_pct`
- `total_effect_pct`

The explicit `*_total_pct` fields are the same domain totals as the nested `totals` block. They are
provided so UI and gateway consumers can render footers and summary-only states without summing the
currently visible rows. This matters when rows are filtered, truncated, or hidden by a downstream
view. The totals are produced by the attribution engine after the selected linking method is applied.

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
      "period": "SI",
      "frequencies": ["daily"]
    }
  ],
  "portfolio_data": {
    "metric_basis": "NET",
    "valuation_points": [
      { "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1018.5 }
    ]
  },
  "instruments_data": [
    {
      "instrument_id": "AAPL",
      "meta": { "sector": "Tech" },
      "valuation_points": [
        { "perf_date": "2025-01-01", "begin_mv": 600, "end_mv": 612 }
      ]
    },
    {
      "instrument_id": "JNJ",
      "meta": { "sector": "Health" },
      "valuation_points": [
        { "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 406.5 }
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
  "benchmark_context": {
    "benchmark_id": "BMK_TECH_1",
    "return_source": "calculated"
  },
  "model": "BF",
  "linking": "none",
  "results_by_period": {
    "SI": {
      "levels": [
        {
          "dimension": "sector",
          "groups": [
            {
              "key": { "sector": "Tech" },
              "portfolio_weight_avg": 60.0,
              "benchmark_weight_avg": 50.0,
              "portfolio_return": 2.0,
              "benchmark_return": 1.5,
              "allocation": -0.05,
              "selection": 0.25,
              "interaction": 0.05,
              "total_effect": 0.25
            },
            {
              "key": { "sector": "Health" },
              "portfolio_weight_avg": 40.0,
              "benchmark_weight_avg": 50.0,
              "portfolio_return": 1.625,
              "benchmark_return": 2.0,
              "allocation": 0.05,
              "selection": -0.1875,
              "interaction": 0.0375,
              "total_effect": -0.1
            }
          ],
          "totals": {
            "allocation": 0.0,
            "selection": 0.0625,
            "interaction": 0.0875,
            "total_effect": 0.15
          },
          "allocation_total_pct": 0.0,
          "selection_total_pct": 0.0625,
          "interaction_total_pct": 0.0875,
          "total_effect_pct": 0.15
        }
      ],
      "reconciliation": {
        "total_active_return": 0.15,
        "sum_of_effects": 0.15,
        "residual": 0.0
      }
    }
  },
  "meta": {
    "calculation_id": "2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e",
    "engine_version": "1.0.0",
    "precision_mode": "FLOAT64",
    "annualization": { "enabled": false, "basis": "BUS/252" },
    "calendar": { "type": "BUSINESS", "trading_calendar": "NYSE" },
    "periods": { "SI": { "start": "2025-01-01", "end": "2025-01-01" } }
  },
  "diagnostics": {
    "nip_days": 0,
    "reset_days": 0,
    "effective_period_start": "2025-01-01",
    "notes": [
      "Period-level status, reason_codes, supportability_evidence, and residual_materiality remain the authoritative attribution degraded-state contract.",
      "Benchmark version, classification version, calendar policy, derivative flags, and short flags are source-limited unless supplied by upstream contracts."
    ],
    "samples": {
      "period_status_counts": [{ "valid": 1 }],
      "residual_materiality_counts": [{ "immaterial": 1 }],
      "supportability_evidence_counts": [
        {
          "portfolio_only_group_count": 0,
          "benchmark_only_group_count": 0,
          "unclassified_group_count": 0
        }
      ]
    }
  },
  "audit": {
    "counts": {
      "input_row_count": 5,
      "portfolio_row_count": 3,
      "benchmark_row_count": 2,
      "resolved_period_count": 1,
      "level_count": 1,
      "group_count": 2,
      "reason_count": 0,
      "supportability_issue_count": 0,
      "periods_with_material_residual": 0,
      "periods_with_watch_residual": 0,
      "benchmark_context_count": 1
    }
  }
}
```

Use `/docs` for exact field-level descriptions and the latest examples.
