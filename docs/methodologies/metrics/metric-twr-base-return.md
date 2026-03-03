## Metric
TWR Base Return (`portfolio_return.base`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/twr`
- Request mode: stateless payload (`valuation_points` provided by caller)
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
- All economic inputs are caller-supplied in `valuation_points[]`.

## Unit Conventions
- `begin_mv`, `end_mv`, `bod_cf`, `eod_cf`, `mgmt_fees` are currency amounts.
- `daily_ror`, `period_return_pct`, `portfolio_return.base` are percentage points (pp).
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
- `r_t`: daily return in decimal
- `r_t_pp`: daily return in pp (`100 * r_t`)
- `R_P_pp`: period-linked return in pp

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

4. Breakdown period return (`period_return_pct` in breakdown summaries):
- Same geometric link from daily `daily_ror` over the aggregation bucket.

## Step-by-Step Computation
1. Validate request (`analyses` non-empty, each `frequencies` non-empty; schema-level field typing).
2. Resolve requested periods using `report_end_date` anchor and `performance_start_date`.
3. Build engine DataFrame from `valuation_points[]` and deduplicate by `perf_date` (keep last).
4. Prepare numeric/date columns, policies, effective-period start dates.
5. Compute `daily_ror` (pp), sign, NIP, cumulative returns, and reset flags.
6. Filter master results to each resolved period.
7. For each non-empty period slice:
- Build requested frequency breakdowns (`period_return_pct`, optional cumulative/annualized fields).
- Compute `portfolio_return.base` using reset-aware or non-reset path.
8. Return `results_by_period` plus diagnostics/meta/audit.

## Validation and Failure Behavior
- `analyses=[]` or any analysis with empty `frequencies[]`: request validation error.
- Invalid/missing `perf_date` after parsing: HTTP 400 (`Invalid Input: One or more 'perf_date' values are invalid or missing.`).
- No resolvable periods: HTTP 400 (`No valid periods could be resolved.`).
- Period resolves but has zero rows after slicing: that period key is omitted from `results_by_period`.
- Zero daily denominator (`abs(begin_mv + bod_cf)=0`): daily return forced to `0` for that row.
- Unexpected engine failures: HTTP 500.

## Configuration Options
- `metric_basis`:
  - `NET`: includes `mgmt_fees` in numerator.
  - `GROSS`: excludes `mgmt_fees`.
- `annualization.enabled`, `annualization.basis`, `annualization.periods_per_year`: controls `annualized_return_pct` in breakdown summaries.
- `output.include_cumulative`: includes `cumulative_return_pct_to_date`.
- `output.include_timeseries`: for daily breakdown only, include raw day row under `daily_data`.
- `reset_policy.emit`: include reset event list per period.
- `data_policy`: can alter input rows before return calculation (overrides/ignore/outlier processing).

## Outputs
Primary fields for this metric:
- `results_by_period.<period>.portfolio_return.base`

Related supporting fields from same computation path:
- `results_by_period.<period>.breakdowns.<frequency>[].summary.period_return_pct`
- `results_by_period.<period>.breakdowns.<frequency>[].summary.cumulative_return_pct_to_date` (optional)
- `results_by_period.<period>.breakdowns.<frequency>[].summary.annualized_return_pct` (optional)

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
- `results_by_period.ITD.portfolio_return.base = 1.6073`
- Daily breakdown entries include each row's `period_return_pct` (`0.8000`, `0.8009`).
