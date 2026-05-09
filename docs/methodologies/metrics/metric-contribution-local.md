## Metric
Position Local Contribution (`position_contributions[].local_contribution`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/contribution`
- Request modes:
  - stateless payload (`stateless_input.portfolio_data`, `stateless_input.positions_data[]`)
  - legacy stateless top-level `portfolio_data` and `positions_data[]`
  - stateful payload (`stateful_input`) resolved from lotus-core portfolio and position timeseries
- Local contribution is meaningful when position daily `local_ror` exists (multi-currency path). If absent, local contribution defaults to zero.

## Inputs
- Position/portfolio valuation points
- `stateful_input.metric_basis`, `stateful_input.dimensions`, `stateful_input.include_cash_flows`,
  and `stateful_input.filters` when source-resolved
- `currency_mode`, `fx`, `hedging`, `report_ccy` (to produce `local_ror` in engine)
- `weighting_scheme`, `smoothing.method`

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; all required values are supplied by the caller.
- Stateful mode resolves lotus-core portfolio and position timeseries and normalizes source rows
  into the same contribution engine request shape. Position source fields can include local,
  portfolio, and reporting-currency market values, `cash_flow_currency`, FX conversion metadata,
  and requested dimensions.
- `lotus-performance` owns local contribution methodology; lotus-core supplies analytics inputs and
  source currency evidence.

## Unit Conventions
- Daily local contribution computed in decimal.
- Response `local_contribution` is percentage points (`decimal * 100`).

## Variable Dictionary
- `w_i,t`: daily position weight
- `l_i,t`: position daily local return (decimal)
- `lc_raw_i,t`: raw local daily contribution
- `lc_s_i,t`: smoothed local daily contribution used for aggregation
- `LC_i`: aggregated position local contribution for period
- `basis`: source-resolved contribution metric basis (`NET` or `GROSS`)

## Methodology and Formulas
1. Daily local contribution:
- `lc_raw_i,t = w_i,t * l_i,t`
- In code: `l_i,t` comes from `local_ror/100`; missing `local_ror` -> `0`

2. Smoothed local contribution:
- `CARINO`: local contribution is not Carino-adjusted directly; implementation keeps
  - `lc_s_i,t = lc_raw_i,t`
- `NONE`: `lc_s_i,t = lc_raw_i,t`

3. NIP/reset handling:
- On portfolio NIP/reset dates, `lc_s_i,t = 0`.

4. Period aggregation:
- `LC_i = sum_t lc_s_i,t`
- Response field: `local_contribution_pp = 100 * LC_i`

## Step-by-Step Computation
1. Resolve mode-specific inputs. In stateful mode retrieve lotus-core portfolio and position
   timeseries, convert source rows into normalized valuation points, and preserve source currency
   and dimension metadata.
2. Produce daily position returns (including `local_ror` when FX path active).
3. Compute daily weights from position vs portfolio BOD capital.
4. Compute `raw_local_contribution` and set `smoothed_local_contribution`.
5. Zero local contributions on NIP/reset dates.
6. Sum per position and map to response (`*100`).

## Validation and Failure Behavior
- Same endpoint validation/failure semantics as total contribution.
- Stateful retrieval or normalization failures block the request rather than falling back to local
  fabricated inputs.
- Stateful `currency_mode=BOTH` requires reporting currency, position currency, and FX rates when
  source position currency differs from the reporting currency.
- If `local_ror` is unavailable, local contribution deterministically evaluates to zero.

## Configuration Options
- `currency_mode`, `fx`, `hedging`, `report_ccy`
- `weighting_scheme`
- `smoothing.method`
- `stateful_input.metric_basis`, `stateful_input.dimensions`, `stateful_input.include_cash_flows`,
  and `stateful_input.filters` when `input_mode=stateful`

## Outputs
- `results_by_period.<period>.position_contributions[].local_contribution`
- Hierarchical: `results_by_period.<period>.summary.local_contribution` and `levels[].rows[].local_contribution` (when `currency_mode=BOTH`)
- `input_mode`
- `calculation_supportability`, `meta`, `diagnostics`, and `audit`

## Worked Example
Two-day example with `w=0.50` and local returns `1.00%`, `0.50%`:

| day | `w_i,t` | `l_i,t` | `lc_raw_i,t` |
|---|---:|---:|---:|
| 1 | 0.50 | 0.0100 | 0.0050 |
| 2 | 0.50 | 0.0050 | 0.0025 |

Aggregation:
- `LC_i = 0.0075` (decimal)
- Response pp: `0.75`

Output mapping:
- `results_by_period.ITD.position_contributions[0].local_contribution = 0.75`
