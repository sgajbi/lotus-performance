## Metric
TWR Local Return (`portfolio_return.local`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/twr`
- Request mode: stateless payload
- Availability condition: local leg is produced only when FX path is active in engine:
  - `currency_mode` is provided and not `BASE_ONLY`, and
  - `fx.rates[]` is provided
- If FX path is not active, local is returned equal to base for period decomposition.

## Inputs
- All base TWR inputs (`valuation_points[]`, dates, analyses, `metric_basis`)
- FX controls used to activate multi-currency path:
  - `currency_mode` (`LOCAL_ONLY` or `BOTH`)
  - `fx.rates[]` (`date`, `ccy`, `rate`)
  - optional `hedging.mode=RATIO`, `hedging.series[]` (affects FX leg, not local equation)

## Upstream Data Sources
- No runtime upstream call.
- Caller-supplied valuation series and FX inputs.

## Unit Conventions
- Local return is output in percentage points.
- Engine computes local daily decimal return first, then multiplies by 100.

## Variable Dictionary
- `B_t`, `E_t`, `CFB_t`, `CFE_t`, `F_t`, `I_NET`, `N_t`, `D_t`: same definitions as base metric
- `l_t`: local daily return (decimal)
- `l_t_pp`: local daily return in pp (`100 * l_t`)
- `L_P_pp`: linked local return for period (pp)

## Methodology and Formulas
1. Daily local return equation is the same valuation equation as base daily numerator/denominator:
- `l_t = N_t / D_t` when `D_t != 0` and row is on/after effective start
- `l_t = 0` otherwise
- `l_t_pp = 100 * l_t`

2. Period local return when no reset day in slice:
- `L_P_pp = 100 * (prod_t(1 + l_t_pp/100) - 1)`

3. Period local return when reset day exists in slice:
- local cumulative ladders (`local_ror_long_cum_ror`, `local_ror_short_cum_ror`) are used.
- Endpoint computes start/end cumulative local totals and rebases:
- `L_P_pp = 100 * (((1 + L_end_pp/100) / (1 + L_start_pp/100)) - 1)`
- If start denominator is zero, implementation returns `L_end_pp` directly.

## Step-by-Step Computation
1. Parse/validate request and resolve periods.
2. Run engine once on master period.
3. In FX-active path, engine writes `local_ror`, `fx_ror`, and `daily_ror` columns.
4. For each resolved non-empty period slice:
- If reset is present: rebase cumulative local return from prior day to slice end.
- Else: geometric-link `local_ror` over the slice.
5. Emit `portfolio_return.local` inside each period result.

## Validation and Failure Behavior
- Same request/period validation as base TWR.
- If FX path is not active (`currency_mode` missing or `BASE_ONLY`, or `fx` block absent):
  - local/fx daily columns are not created.
  - endpoint returns `portfolio_return.local = portfolio_return.base` and `portfolio_return.fx = 0.0`.
- Zero denominator rows force local daily return to zero.
- Unexpected processing failures map to HTTP 500.

## Configuration Options
- `currency_mode` controls whether multi-currency decomposition path is considered.
- `fx.rates[]` is required in practice to activate local/fx decomposition branch.
- `metric_basis` still affects local numerator via fee inclusion for `NET`.
- `reset_policy.emit` only affects reset-event reporting, not local return math.

## Outputs
Primary metric field:
- `results_by_period.<period>.portfolio_return.local`

Related fields:
- `results_by_period.<period>.portfolio_return.base`
- `results_by_period.<period>.portfolio_return.fx`

## Worked Example
FX-active sample (`currency_mode=BOTH`, `metric_basis=GROSS`):

| t | B_t | CFB_t | CFE_t | F_t | E_t | N_t | D_t | l_t_pp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1000.00 | 0.00 | 0.00 | 0.00 | 1020.00 | 20.00 | 1000.00 | 2.0000 |
| 2 | 1020.00 | 0.00 | 0.00 | 0.00 | 1030.20 | 10.20 | 1020.00 | 1.0000 |

Intermediate link:
- `L_P_pp = 100 * ((1 + 2.0000/100) * (1 + 1.0000/100) - 1)`
- `L_P_pp = 3.0200 pp`

Output mapping:
- `results_by_period.ITD.portfolio_return.local = 3.0200`
