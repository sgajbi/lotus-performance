## Metric
TWR FX Return (`portfolio_return.fx`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/twr`
- Request mode: stateless payload
- Availability condition: FX leg exists only when engine FX path is active:
  - `currency_mode` provided and not `BASE_ONLY`
  - `fx.rates[]` present
- If FX path is inactive, `portfolio_return.fx` is `0.0`.

## Inputs
- `valuation_points[]` (for local/base return context)
- `performance_start_date` (used to build one-day lookback for start rates)
- `currency_mode`
- `fx.rates[]`: each row has `date`, `ccy`, `rate`
- Optional hedge inputs:
  - `hedging.mode=RATIO`
  - `hedging.series[]` with `date`, `ccy`, `hedge_ratio` in `[0,1]`

## Upstream Data Sources
- No runtime upstream call.
- FX time series is client-supplied via request.

## Unit Conventions
- FX daily and period returns are percentage points in outputs.
- Internal rate ratios are decimal values before conversion to pp.

## Variable Dictionary
- `S_t`: start FX rate for day `t` (rate at `t-1` after forward-fill reindex)
- `E_t`: end FX rate for day `t` (rate at `t` after forward-fill reindex)
- `h_t`: hedge ratio for day `t` (default `0` when missing)
- `f_t`: unhedged daily FX return in decimal
- `f_t_hedged`: hedged daily FX return in decimal
- `f_t_pp`: daily FX return in pp
- `R_base_pp`: period base return in pp
- `R_local_pp`: period local return in pp
- `F_P_pp`: period FX return in pp

## Methodology and Formulas
1. Build aligned FX curve from `fx.rates[]`:
- de-duplicate by (`date`,`ccy`) keeping last
- set index by date and forward-fill over full daily range from `performance_start_date - 1` to max perf date

2. Daily FX return (engine):
- `f_t = (E_t / S_t) - 1`
- missing values are filled with `0`
- if hedge series provided: `f_t_hedged = f_t * (1 - h_t)` else `f_t_hedged = f_t`
- `f_t_pp = 100 * f_t_hedged`

3. Period FX return (endpoint decomposition):
- First compute period base and local totals.
- `F_P_pp = 100 * (((1 + R_base_pp/100) / (1 + R_local_pp/100)) - 1)`
- If `1 + R_local_pp/100 == 0`, implementation returns `0.0` for FX period return.

## Step-by-Step Computation
1. Validate base request and resolve periods.
2. Activate FX path only if `currency_mode != BASE_ONLY` and `fx` block exists.
3. Construct start/end rates per valuation date from forward-filled rate timeline.
4. Compute daily `fx_ror` (and apply hedge if provided).
5. Compute slice-level `portfolio_return.base` and `portfolio_return.local`.
6. Derive `portfolio_return.fx` from base/local decomposition identity.

## Validation and Failure Behavior
- Same base endpoint validation and error handling.
- Missing or non-active FX inputs do not error by themselves; FX metric becomes `0.0` because local/fx columns are absent.
- Missing daily rate points are forward-filled on constructed daily range; unresolved values are treated as zero-return rows.
- If local period denominator is zero in decomposition formula, FX period return is forced to `0.0`.

## Configuration Options
- `currency_mode`: must be non-`BASE_ONLY` for FX decomposition path.
- `fx.rates[]`: determines FX leg behavior and continuity via forward-fill.
- `hedging.series[]`: scales FX daily returns by `(1 - hedge_ratio)`.
- `metric_basis`, `data_policy`, `annualization`, and output flags affect base/local context and breakdowns.

## Outputs
Primary metric field:
- `results_by_period.<period>.portfolio_return.fx`

Supporting fields used in decomposition identity:
- `results_by_period.<period>.portfolio_return.base`
- `results_by_period.<period>.portfolio_return.local`

## Worked Example
Assume for period `ITD` after linking daily rows:
- `R_local_pp = 3.0200`
- `R_base_pp = 4.98228`

Intermediate decomposition:

| Quantity | Formula | Value |
|---|---|---:|
| Local growth factor | `1 + R_local_pp/100` | 1.0302000 |
| Base growth factor | `1 + R_base_pp/100` | 1.0498228 |
| FX growth factor | `Base / Local` | 1.0190476 |
| `F_P_pp` | `100 * (FX growth factor - 1)` | 1.90476 |

Output mapping:
- `results_by_period.ITD.portfolio_return.fx = 1.90476`
