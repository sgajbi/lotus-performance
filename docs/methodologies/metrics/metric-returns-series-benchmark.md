## Metric
Canonical Benchmark Return Series (`series.benchmark_returns`)

## Endpoint and Mode Coverage
- Endpoint: `POST /integration/returns/series`
- Inclusion condition: `series_selection.include_benchmark=true`
- Modes:
  - `stateless`: request supplies `benchmark_returns`
  - `stateful`: lotus-core benchmark assignment is resolved and benchmark returns are sourced or calculated through the shared benchmark path

## Inputs
- Shared controls: `window`, `frequency`, `data_policy`, `as_of_date`
- Stateless benchmark input: `stateless_input.benchmark_returns[]`
- Stateful benchmark controls:
  - optional `benchmark.benchmark_id`
  - if missing, benchmark assignment lookup by portfolio

## Upstream Data Sources
- Stateless: request payload.
- Stateful:
  - `get_benchmark_assignment` (when benchmark id not provided)
  - `build_stateful_benchmark_input` for calculated benchmark mode
  - `get_benchmark_return_series` only for explicit `benchmark.return_source="vendor_series"`

## Unit Conventions
- Benchmark return points are decimal returns (`0.0012 = 12 bps`).
- Aggregation uses geometric linking in decimal space.

## Variable Dictionary
- `b_t`: daily benchmark return (decimal)
- `B_k`: aggregated benchmark return for bucket `k`
- `W`: resolved window

## Methodology and Formulas
1. Normalize benchmark points:
- stateless: from `ReturnPoint`
- stateful: normalize upstream fields (`series_date`, `benchmark_return`)
- reject duplicates and empty lists

2. Filter to window `W` and sort by date.

3. Resample by frequency:
- `DAILY`: unchanged
- `WEEKLY`/`MONTHLY`: `B_k = prod_{t in k}(1 + b_t) - 1`

4. Apply post-processing policies relative to portfolio dates:
- strict intersection
- optional forward-fill / zero-fill reindexing

## Step-by-Step Computation
1. Validate request and resolve window.
2. Retrieve benchmark source data (stateless or stateful).
3. Normalize to canonical DataFrame, enforce uniqueness, and window filter.
4. Resample to requested frequency.
5. Apply data-policy alignment/fill rules.
6. Serialize as `series.benchmark_returns`.
7. When benchmark resolution happened in stateful mode, also emit `benchmark_context` with the resolved benchmark id and return-source mode.

## Validation and Failure Behavior
- `include_benchmark=true` with missing stateless benchmark input: validation error.
- Stateful assignment not found: HTTP 404.
- Stateful benchmark source unavailable: HTTP 503.
- Upstream payload missing required `points` list: HTTP 422 (`CONTRACT_VIOLATION_UPSTREAM`).
- No observations in resolved window: HTTP 422 (`INSUFFICIENT_DATA`).

## Configuration Options
- `series_selection.include_benchmark`
- `benchmark.benchmark_id`
- `window.*`, `frequency`
- `data_policy.missing_data_policy`, `fill_method`, `calendar_policy`

## Outputs
Primary metric field:
- `series.benchmark_returns[]` (`date`, `return_value` decimal)
- `benchmark_context` (`benchmark_id`, `return_source`) when stateful resolution selected a benchmark

Diagnostics impact:
- benchmark gaps are included in `diagnostics.gaps[]`
- alignment/fill affects returned benchmark points

## Worked Example
Daily benchmark points:

| date | `b_t` |
|---|---:|
| 2026-02-26 | 0.0010 |
| 2026-02-27 | 0.0020 |

Two-day linked return:
- `B = (1.0010 * 1.0020) - 1 = 0.003002`

Output mapping (if weekly/monthly bucketed to single period):
- `series.benchmark_returns[0].return_value = 0.003002`
