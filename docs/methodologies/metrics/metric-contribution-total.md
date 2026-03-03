## Metric
Position Total Contribution (`position_contributions[].total_contribution`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/contribution`
- Mode: stateless request payload (`portfolio_data`, `positions_data`)
- Output shapes:
  - flat position output when `hierarchy` is null
  - hierarchical output when `hierarchy` is provided

## Inputs
- `portfolio_data.valuation_points[]`
- `positions_data[].valuation_points[]`
- `analyses[]` (period resolution)
- `weighting_scheme` (implemented branch: `BOD`)
- `smoothing.method` (`CARINO` or `NONE`)
- Optional FX controls influencing underlying returns: `currency_mode`, `fx`, `hedging`, `report_ccy`

## Upstream Data Sources
- No runtime upstream dependency; all inputs are request-supplied.

## Unit Conventions
- Daily contribution math in engine uses decimal form.
- Response fields are scaled to percentage points by multiplying decimal totals by `100`.

## Variable Dictionary
- `B_i,t`: position beginning MV
- `CFB_i,t`: position BOD cash flow
- `B_P,t`: portfolio beginning MV
- `CFB_P,t`: portfolio BOD cash flow
- `w_i,t`: daily weight for position `i`
- `r_i,t`: position daily return (decimal)
- `c_raw_i,t`: raw daily contribution (decimal)
- `c_s_i,t`: smoothed daily contribution (decimal)
- `R_P,t`: portfolio daily return (decimal)
- `R_P`: linked portfolio period return (decimal)
- `K_t`: Carino daily factor
- `K`: Carino total factor

## Methodology and Formulas
1. Daily weight (`BOD` branch):
- `capital_i,t = B_i,t + CFB_i,t`
- `capital_P,t = B_P,t + CFB_P,t`
- `w_i,t = capital_i,t / capital_P,t` (NaN/inf -> `0`)

2. Raw daily contribution:
- `c_raw_i,t = w_i,t * r_i,t`

3. Carino smoothing branch (`smoothing.method=CARINO`):
- `K_t = log(1 + R_P,t) / R_P,t` (if `R_P,t=0`, use `1`)
- `R_P = prod_t(1 + R_P,t) - 1`
- `K = log(1 + R_P) / R_P` (if `R_P=0`, use `1`)
- `adjust_i,t = w_i,t * (R_P,t * (K / K_t - 1))`
- `c_s_i,t = c_raw_i,t + adjust_i,t`

4. Non-Carino branch:
- `c_s_i,t = c_raw_i,t`

5. NIP/reset day handling:
- For dates where portfolio has `NIP=1` or `PERF_RESET=1`, set daily contributions to `0`.

6. Period aggregation:
- Position period contribution (decimal): `C_i = sum_t c_s_i,t`
- Portfolio period return from portfolio daily series: `R_P = prod_t(1 + R_P,t) - 1`
- Sum-of-parts residual: `residual = R_P - sum_i C_i`
- If `CARINO` and `sum_i avg_weight_i > 0`, allocate residual by average weight proportion.

## Step-by-Step Computation
1. Resolve requested periods.
2. Run TWR engine for portfolio and each position to obtain daily returns.
3. Merge position rows with portfolio capital columns by date.
4. Compute daily weights and raw daily contributions.
5. Apply smoothing method (`CARINO` or `NONE`).
6. Zero contribution rows on NIP/reset dates.
7. Slice by period, aggregate by position, and apply residual reconciliation when applicable.
8. Convert decimal contributions to pp in response (`*100`).

## Validation and Failure Behavior
- Empty `analyses` is request validation error.
- No resolved periods: HTTP 400.
- Empty period slice: period omitted from `results_by_period`.
- Division by zero in weights is tolerated and mapped to zero weight.
- Unexpected runtime failure: HTTP 500.

## Configuration Options
- `weighting_scheme` (implemented logic uses `BOD` capital definitions)
- `smoothing.method` (`CARINO` enables smoothing + residual allocation)
- `hierarchy` (changes response shape and aggregation path)
- `currency_mode`/`fx`/`hedging`/`report_ccy` (changes underlying return decomposition)

## Outputs
Primary fields:
- `results_by_period.<period>.position_contributions[].total_contribution`
- `results_by_period.<period>.total_contribution`
- `results_by_period.<period>.total_portfolio_return`

Hierarchical path fields:
- `results_by_period.<period>.summary.portfolio_contribution`
- `results_by_period.<period>.levels[].rows[].contribution`

## Worked Example
Two-day single-position example (`smoothing=NONE`):

| day | `w_i,t` | `r_i,t` | `c_raw_i,t` |
|---|---:|---:|---:|
| 1 | 0.60 | 0.0100 | 0.0060 |
| 2 | 0.60 | 0.0200 | 0.0120 |

Aggregation:
- `C_i = 0.0060 + 0.0120 = 0.0180` (decimal)
- Response value in pp: `0.0180 * 100 = 1.80`

Output mapping:
- `results_by_period.ITD.position_contributions[0].total_contribution = 1.80`
