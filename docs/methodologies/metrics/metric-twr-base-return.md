## Metric
TWR Base Return (`portfolio.summary.period_return.base`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/twr`
- Request mode:
  - stateless payload (`valuation_points` or `stateless_input.valuation_points`)
  - stateful payload (`stateful_input`) sourced from lotus-core and normalized into valuation points by lotus-performance
- Availability: always computed for each resolved period that has at least one valuation row in-range

## Inputs
- `portfolio_id`
- `performance_start_date`
- `report_end_date`
- `analyses[]` (each item: `period`, `frequencies[]`)
- `valuation_points[]` with per-row fields:
  - `perf_date`
  - `begin_mv`
  - `bod_cf`
  - `eod_cf`
  - `mgmt_fees`
  - `end_mv`
- `metric_basis` (`NET` or `GROSS`)
- Optional calculation controls: `annualization`, `rounding_precision`, `data_policy`, `reset_policy.emit`, `output.include_cumulative`, `output.include_timeseries`

## Upstream Data Sources
- No runtime cross-service dependency.
- In stateless mode, all economic inputs are caller-supplied in `valuation_points[]`.
- In stateful mode, the same economic inputs are sourced from lotus-core portfolio timeseries and normalized into `valuation_points[]` before engine execution.

## Unit Conventions
- `begin_mv`, `end_mv`, `bod_cf`, `eod_cf`, `mgmt_fees` are currency amounts.
- `daily_ror`, `period_return.base`, and `cumulative_return.base` are percentage points (pp).
- Geometric linking uses decimal growth internally: `(1 + return_pp/100)`.

## Variable Dictionary
- `B_t`: `begin_mv` on day `t`
- `E_t`: `end_mv` on day `t`
- `CFB_t`: `bod_cf` on day `t`
- `CFE_t`: `eod_cf` on day `t`
- `F_t`: `mgmt_fees` on day `t`
- `I_NET`: indicator, `1` when `metric_basis=NET`, else `0`
- `N_t`: daily numerator `E_t - CFB_t - B_t - CFE_t + I_NET * F_t`
- `D_t`: daily denominator `abs(B_t + CFB_t)`
- `r_t`: daily base return in decimal
- `r_t_pp`: daily return in pp (`100 * r_t`)
- `C_start_pp`: cumulative base return in pp on the day before the slice start after reset processing
- `C_end_pp`: cumulative base return in pp on the slice end date after reset processing
- `R_P_pp`: period-linked base return in pp

## Methodology and Formulas
1. Daily base return (engine `calculate_daily_ror`):
- `r_t = N_t / D_t` when `D_t != 0` and `perf_date_t >= effective_period_start_date_t`
- `r_t = 0` otherwise
- `r_t_pp = 100 * r_t`

2. Period base return without resets (`_calculate_total_return_from_non_reset_slice`):
- `R_P_pp = 100 * (prod_t(1 + r_t_pp/100) - 1)`

3. Period base return with reset days present (`_calculate_total_return_from_reset_slice`):
- Let `C_start_pp` = prior day cumulative base return before period slice (or `0` if none)
- Let `C_end_pp` = cumulative base return at period-slice end
- `R_P_pp = 100 * (((1 + C_end_pp/100) / (1 + C_start_pp/100)) - 1)`
- If `(1 + C_start_pp/100) == 0`, implementation returns `C_end_pp` directly.

4. Breakdown period return (`period_return.base` in comparative breakdown rows):
- Same geometric link from daily `daily_ror` over the aggregation bucket.

## Step-by-Step Computation
1. Validate request (`analyses` non-empty, each `frequencies` non-empty; schema-level field typing).
2. Resolve requested periods using `report_end_date` anchor and `performance_start_date`.
3. Build engine DataFrame from `valuation_points[]` and deduplicate by `perf_date` (keep last).
4. Prepare numeric/date columns, policies, effective-period start dates.
5. Compute `daily_ror` (pp), sign, NIP, cumulative returns, and reset flags.
6. Filter master results to each resolved period.
7. For each non-empty period slice:
- Build requested frequency breakdowns (`period_return.base`, optional cumulative/annualized fields).
- Compute `portfolio.summary.period_return.base` using reset-aware or non-reset path.
- If the slice contains any `perf_reset=1` row, rebase the slice return from cumulative return state; otherwise compound daily `daily_ror` directly.
8. Return `results_by_period` plus diagnostics/meta/audit.

## Validation and Failure Behavior
- `analyses=[]` or any analysis with empty `frequencies[]`: request validation error.
- Invalid/missing `perf_date` after parsing: HTTP 400 (`Invalid Input: One or more 'perf_date' values are invalid or missing.`).
- No resolvable periods: HTTP 400 (`No valid periods could be resolved.`).
- Period resolves but has zero rows after slicing: that period key is omitted from `results_by_period`.
- Zero daily denominator (`abs(begin_mv + bod_cf)=0`): daily return forced to `0` for that row.
- Rows before `effective_period_start_date` are also forced to zero daily return by the engine.
- Unexpected engine failures: HTTP 500.

## Configuration Options
- `metric_basis`:
  - `NET`: includes `mgmt_fees` in numerator.
  - `GROSS`: excludes `mgmt_fees`.
- RFC-021 boundary: this metric supports fee-basis return treatment only. It does not consume a
  shared `costs` request block, emit a `gross_net` bridge, or compute performance-fee HWM/hurdle,
  transaction-cost, or tax effects.
- `annualization.enabled`, `annualization.basis`, `annualization.periods_per_year`: controls `annualized_return_pct` in breakdown summaries.
- `output.include_cumulative`: includes comparative `cumulative_return.base` fields in breakdown rows.
- `output.include_timeseries`: for daily breakdown only, include raw day row under `daily_data`.
- `reset_policy.emit`: include reset event list per period.
- `data_policy`: can alter input rows before return calculation (overrides/ignore/outlier processing).

## Outputs
Primary fields for this metric:
- `results_by_period.<period>.portfolio.summary.period_return.base`
- `results_by_period.<period>.portfolio.summary.cumulative_return.base`

Related supporting fields from same computation path:
- `results_by_period.<period>.portfolio.breakdowns.<frequency>[].period_return.base`
- `results_by_period.<period>.portfolio.breakdowns.<frequency>[].cumulative_return.base` (optional)
- `results_by_period.<period>.portfolio.breakdowns.<frequency>[].annualized_return.base` (optional)
- `results_by_period.<period>.reset_events[]` when `reset_policy.emit=true`

## Worked Example
Sample input rows (`metric_basis=NET`):

| t | perf_date | B_t | CFB_t | CFE_t | F_t | E_t | N_t | D_t | r_t_pp |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2026-01-02 | 1000.00 | 0.00 | 0.00 | -1.00 | 1009.00 | 8.00 | 1000.00 | 0.8000 |
| 2 | 2026-01-03 | 1009.00 | 0.00 | 0.00 | -1.00 | 1018.0810 | 8.0810 | 1009.00 | 0.8009 |

Intermediate link (no reset in slice):
- `R_P_pp = 100 * ((1 + 0.8000/100) * (1 + 0.8009/100) - 1)`
- `R_P_pp = 1.6073 pp` (rounded)

Output mapping:
- `results_by_period.ITD.portfolio.summary.period_return.base = 1.6073`
- `results_by_period.ITD.portfolio.summary.cumulative_return.base = 1.6073`
- Daily breakdown entries include each row's `period_return.base` (`0.8000`, `0.8009`).
