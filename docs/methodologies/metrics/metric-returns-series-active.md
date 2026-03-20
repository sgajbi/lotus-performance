## Metric
Canonical Active Return Series (`series.active_returns`) and Cumulative Active Return Series (`series.cumulative_active_returns`)

## Endpoint and Mode Coverage
- Endpoint: `POST /integration/returns/series`
- Inclusion condition:
  - `series_selection.include_portfolio=true`
  - `series_selection.include_benchmark=true`
- Modes:
  - `stateless`: request supplies aligned or alignable portfolio and benchmark returns
  - `stateful`: lotus-performance derives portfolio returns and benchmark returns, then emits active returns from the resolved series

## Inputs
- Shared controls:
  - `window`, `frequency`, `data_policy`, `as_of_date`
- Portfolio series source:
  - `stateless_input.portfolio_returns[]`
  - or stateful portfolio sourcing from lotus-core
- Benchmark series source:
  - `stateless_input.benchmark_returns[]`
  - or stateful benchmark assignment / benchmark series sourcing

## Upstream Data Sources
- Stateless: request payload only.
- Stateful:
  - lotus-core portfolio analytics timeseries
  - lotus-core benchmark assignment when no explicit benchmark override is supplied
  - lotus-core benchmark composition / price / FX inputs for calculated benchmark mode, or benchmark return series for explicit vendor-series mode

## Unit Conventions
- Active return points are decimal returns, not percentage points.
- `0.0015` means 15 bps of arithmetic excess return for the date bucket.

## Variable Dictionary
- `p_t`: portfolio return for date or bucket `t`
- `b_t`: benchmark return for date or bucket `t`
- `a_t`: active return for date or bucket `t`
- `P_t`: cumulative portfolio return through date or bucket `t`
- `B_t`: cumulative benchmark return through date or bucket `t`
- `A_t`: cumulative active return through date or bucket `t`
- `W`: resolved date window

## Methodology and Formulas
1. Build canonical portfolio return series `p_t`.
2. Build canonical benchmark return series `b_t`.
3. Align both series on common emitted dates after windowing, resampling, and data-policy application.
4. Compute arithmetic active return:
- `a_t = p_t - b_t`

5. Compute cumulative portfolio and benchmark ladders:
- `P_t = Π(1 + p_i) - 1` for all emitted rows `i <= t`
- `B_t = Π(1 + b_i) - 1` for all emitted rows `i <= t`

6. Compute cumulative active return arithmetically:
- `A_t = P_t - B_t`

The point active series is intentionally arithmetic active return, not geometrically linked excess return.
The cumulative active series is the arithmetic excess of the cumulative portfolio and cumulative benchmark ladders.

## Step-by-Step Computation
1. Validate request contract and resolve the date window.
2. Derive or source portfolio returns.
3. Derive or source benchmark returns.
4. Apply requested frequency aggregation to each series independently.
5. Apply post-processing alignment and fill policy to benchmark/risk-free relative to the portfolio series.
6. Inner-join portfolio and benchmark outputs on final emitted dates.
7. Subtract benchmark returns from portfolio returns date by date.
8. Emit the result as `series.active_returns`.
9. Geometrically link portfolio and benchmark returns independently through each emitted row date.
10. Subtract cumulative benchmark return from cumulative portfolio return date by date.
11. Emit the result as `series.cumulative_active_returns`.

## Validation and Failure Behavior
- If no benchmark series is requested, both `series.active_returns` and `series.cumulative_active_returns` are omitted.
- If benchmark series is requested but unavailable, the enclosing request fails with the same benchmark error path used for `series.benchmark_returns`.
- If post-policy alignment leaves no common portfolio/benchmark dates, both active series are omitted rather than synthesized.
- Missing-data and fill-policy behavior is inherited from the benchmark and portfolio return series normalization path.

## Configuration Options
- `series_selection.include_benchmark`
- `window.*`, `frequency`
- `data_policy.missing_data_policy`
- `data_policy.fill_method`
- `data_policy.calendar_policy`
- `benchmark.benchmark_id`
- `benchmark.return_source`

## Outputs
Primary metric field:
- `series.active_returns[]` (`date`, `return_value` decimal)
- `series.cumulative_active_returns[]` (`date`, `return_value` decimal)

Relationship to sibling metrics:
- `series.portfolio_returns[]`
- `series.benchmark_returns[]`
- `series.cumulative_portfolio_returns[]`
- `series.cumulative_benchmark_returns[]`

## Worked Example
Given aligned daily returns:

| date | portfolio `p_t` | benchmark `b_t` | active `a_t = p_t - b_t` |
|---|---:|---:|---:|
| 2026-02-23 | 0.0100 | 0.0010 | 0.0090 |
| 2026-02-24 | 0.0050 | 0.0050 | 0.0000 |
| 2026-02-25 | -0.0025 | -0.0025 | 0.0000 |

Output mapping:
- `series.active_returns[0].date = 2026-02-23`
- `series.active_returns[0].return_value = 0.0090`
- `series.cumulative_active_returns[0].date = 2026-02-23`
- `series.cumulative_active_returns[0].return_value = 0.0090`
