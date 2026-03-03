## Metric
Attribution Total Active Return (`reconciliation.total_active_return`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Modes:
  - `mode=BY_GROUP` (pre-aggregated portfolio groups provided)
  - `mode=BY_INSTRUMENT` (engine builds grouped portfolio panel from instrument valuation series)
- Calculated per resolved period in `results_by_period`.

## Inputs
- `benchmark_groups_data[]` with group/date `weight_bop`, `return_base`
- Portfolio side from either:
  - `portfolio_groups_data[]` (`BY_GROUP`), or
  - `portfolio_data` + `instruments_data[]` (`BY_INSTRUMENT`)
- `group_by[]`, `frequency`, `model`, `linking`

## Upstream Data Sources
- Request payload only; no runtime upstream service dependency.

## Unit Conventions
- Engine computations are decimal returns.
- Response reconciliation values are converted to percentage points (`*100`).

## Variable Dictionary
- `w_p,g,t`: portfolio BOP weight for group `g`, period `t`
- `w_b,g,t`: benchmark BOP weight for group `g`, period `t`
- `r_p,g,t`: portfolio group base return (decimal)
- `r_b,g,t`: benchmark group base return (decimal)
- `r_b,t`: benchmark total return for period `t` (weighted group sum)
- `R_p,t`: portfolio aggregate return per period `t`
- `R_b,t`: benchmark aggregate return per period `t`
- `AR_t`: active return per period `t`
- `AR`: total active return across linked horizon

## Methodology and Formulas
1. Per-period aggregate returns:
- `R_p,t = sum_g(w_p,g,t * r_p,g,t)`
- `R_b,t = r_b,t` where `r_b,t = sum_g(w_b,g,t * r_b,g,t)`
- `AR_t = R_p,t - R_b,t`

2. Total active return by linking mode:
- `linking=NONE`: `AR = sum_t AR_t`
- `linking!=NONE`: `AR = (prod_t(1+R_p,t)-1) - (prod_t(1+R_b,t)-1)`

3. Reconciliation block:
- `total_active_return = 100 * AR`
- `sum_of_effects = allocation + selection + interaction` totals (already scaled to pp)
- `residual = total_active_return - sum_of_effects`

## Step-by-Step Computation
1. Resolve requested periods and create master request window.
2. Build aligned portfolio/benchmark panel at requested frequency.
3. Compute single-period effects, then aggregate by period slice.
4. Compute portfolio and benchmark per-period aggregate returns.
5. Compute total active return according to `linking` mode.
6. Populate reconciliation fields in response.

## Validation and Failure Behavior
- No resolved periods: HTTP 400.
- Invalid attribution mode: HTTP 400.
- Empty aligned panel or empty period slice: period omitted from output.
- Engine/input errors surface as HTTP 400/500 depending on exception type.

## Configuration Options
- `linking` (`NONE` vs non-`NONE` geometric active return path)
- `frequency` (daily/monthly/quarterly/yearly resampling)
- `mode`, `group_by`, `model`

## Outputs
- `results_by_period.<period>.reconciliation.total_active_return`
- `results_by_period.<period>.reconciliation.sum_of_effects`
- `results_by_period.<period>.reconciliation.residual`

## Worked Example
Assume two sub-periods:

| t | `R_p,t` | `R_b,t` | `AR_t` |
|---|---:|---:|---:|
| 1 | 0.0200 | 0.0150 | 0.0050 |
| 2 | 0.0100 | 0.0080 | 0.0020 |

- Arithmetic active (`NONE`): `AR = 0.0050 + 0.0020 = 0.0070`
- Geometric active (linked): `AR = (1.02*1.01-1) - (1.015*1.008-1) = 0.00697`

Output mapping (linked case):
- `reconciliation.total_active_return = 0.00697 * 100 = 0.697`
