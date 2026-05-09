## Metric
Position Total Contribution (`position_contributions[].total_contribution`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/contribution`
- Request modes:
  - stateless payload (`stateless_input.portfolio_data`, `stateless_input.positions_data[]`)
  - legacy stateless top-level `portfolio_data` and `positions_data[]`
  - stateful payload (`stateful_input`) resolved from lotus-core portfolio and position timeseries
- Output shapes:
  - flat position output when `hierarchy` is null
  - hierarchical output when `hierarchy` is provided
- Period coverage:
  - both flat and hierarchical paths resolve `analyses[]` into `results_by_period`
  - each resolved period is aggregated independently from the same master-window daily contribution set

## Inputs
- `portfolio_data.valuation_points[]`
- `positions_data[].valuation_points[]`
- `stateful_input.metric_basis` (`NET` or `GROSS`) when source-resolved
- `stateful_input.dimensions[]`, `stateful_input.include_cash_flows`, and `stateful_input.filters`
  when source-resolved
- `analyses[]` (period resolution)
- `weighting_scheme` (implemented branch: `BOD`)
- `smoothing.method` (`CARINO` or `NONE`)
- Optional FX controls influencing underlying returns: `currency_mode`, `fx`, `hedging`, `report_ccy`

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; all required values are supplied by the caller.
- Stateful mode resolves source input from lotus-core portfolio and position timeseries through the
  stateful input service. The resolver retrieves portfolio observations, position rows,
  dimensions, optional cash-flow rows, filters, retrieval metadata, and source currency fields,
  then normalizes them into the same `ContributionRequest` shape used by stateless execution.
- `lotus-performance` remains the contribution methodology owner; lotus-core supplies analytics
  inputs and source metadata, not contribution conclusions.

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
- `basis`: source-resolved contribution metric basis (`NET` or `GROSS`)
- `M_i`: source metadata attached to position `i`, including dimensions and selected currency
  evidence where available

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
- Hierarchical period aggregation uses the same period slice:
  - aggregate position contributions to `summary.portfolio_contribution`
  - roll up by `hierarchy[]` levels from `position_id` metadata
  - emit one hierarchy summary per resolved period, not one master-window hierarchy

## Step-by-Step Computation
1. Resolve mode-specific inputs. In stateful mode retrieve lotus-core portfolio and position
   timeseries, normalize source rows into `portfolio_data` and `positions_data`, preserve source
   dimensions in position metadata, and convert source cash-flow rows into BOD, EOD, and fee fields.
2. Resolve requested periods.
3. Run TWR engine for portfolio and each position to obtain daily returns.
4. Merge position rows with portfolio capital columns by date.
5. Compute daily weights and raw daily contributions.
6. Apply smoothing method (`CARINO` or `NONE`).
7. Zero contribution rows on NIP/reset dates.
8. Slice both contribution rows and portfolio daily-return rows by each resolved period.
9. Aggregate by position or hierarchy within that period slice and apply residual reconciliation when applicable.
10. Convert decimal contributions to pp in response (`*100`).

## Validation and Failure Behavior
- Empty `analyses` is request validation error.
- Stateful mode rejects missing `stateful_input`, rejects stateless payloads in stateful mode, and
  fails through the retrieval or normalization stage when lotus-core source data cannot produce
  usable portfolio or position inputs.
- Stateful `currency_mode=BOTH` requires reporting currency, position currency, and FX rates when
  source position currency differs from the reporting currency.
- Source rows without usable dates or market values are skipped during normalization rather than
  guessed.
- No resolved periods: HTTP 400.
- Empty period slice: period omitted from `results_by_period`.
- Division by zero in weights is tolerated and mapped to zero weight.
- Unexpected runtime failure: HTTP 500.

## Configuration Options
- `weighting_scheme` (implemented logic uses `BOD` capital definitions)
- `smoothing.method` (`CARINO` enables smoothing + residual allocation)
- `hierarchy` (changes response shape and aggregation path)
- `currency_mode`/`fx`/`hedging`/`report_ccy` (changes underlying return decomposition)
- `stateful_input.metric_basis`, `stateful_input.dimensions`, `stateful_input.include_cash_flows`,
  and `stateful_input.filters` when `input_mode=stateful`

## Outputs
Primary fields:
- `results_by_period.<period>.position_contributions[].total_contribution`
- `results_by_period.<period>.total_contribution`
- `results_by_period.<period>.total_portfolio_return`
- `input_mode`
- `calculation_supportability`, `meta`, `diagnostics`, and `audit`

Hierarchical path fields:
- `results_by_period.<period>.summary.portfolio_contribution`
- `results_by_period.<period>.levels[].rows[].contribution`
- `results_by_period.<period>.summary.local_contribution` and `fx_contribution` when `currency_mode=BOTH`

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
- In hierarchy mode, the same period slice would map to `results_by_period.ITD.summary.portfolio_contribution = 1.80`
