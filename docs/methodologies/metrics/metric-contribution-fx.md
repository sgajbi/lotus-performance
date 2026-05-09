## Metric
Position FX Contribution (`position_contributions[].fx_contribution`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/contribution`
- Request modes:
  - stateless payload (`stateless_input.portfolio_data`, `stateless_input.positions_data[]`)
  - legacy stateless top-level `portfolio_data` and `positions_data[]`
  - stateful payload (`stateful_input`) resolved from lotus-core portfolio and position timeseries
- FX contribution is decomposition residual between total and local contribution in period aggregation.

## Inputs
- Position daily total contribution components
- Position daily local contribution components
- `stateful_input.metric_basis`, `stateful_input.dimensions`, `stateful_input.include_cash_flows`,
  and `stateful_input.filters` when source-resolved
- `currency_mode`, `fx`, `hedging`, `report_ccy`
- `smoothing.method`

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; all required values are supplied by the caller.
- Stateful mode resolves lotus-core portfolio and position timeseries and normalizes source rows
  into the same contribution engine request shape. Position source rows can include local,
  portfolio, and reporting-currency values plus FX conversion metadata used to support
  `currency_mode=BOTH`.
- `lotus-performance` owns FX contribution decomposition; lotus-core supplies analytics inputs and
  source currency evidence.

## Unit Conventions
- Internal contribution values are decimals.
- Response `fx_contribution` values are percentage points (`decimal * 100`).

## Variable Dictionary
- `C_i`: aggregated total contribution (decimal)
- `LC_i`: aggregated local contribution (decimal)
- `FX_i`: aggregated FX contribution (decimal)
- `c_s_i,t`: smoothed daily total contribution
- `lc_s_i,t`: smoothed daily local contribution
- `fx_s_i,t`: smoothed daily FX contribution
- `basis`: source-resolved contribution metric basis (`NET` or `GROSS`)

## Methodology and Formulas
1. Daily construction in engine:
- `fx_raw_i,t = w_i,t * fx_ror_i,t`
- `CARINO` branch:
  - `fx_s_i,t = c_s_i,t - lc_s_i,t`
- `NONE` branch:
  - `fx_s_i,t = fx_raw_i,t`

2. NIP/reset handling:
- On portfolio NIP/reset dates, daily FX contribution is set to `0`.

3. Period aggregation in endpoint (flat path):
- `FX_i = C_i - LC_i`
- Response value: `fx_contribution_pp = 100 * FX_i`

4. Hierarchical aggregation:
- Aggregate position-level `fx_contribution` sums into summary/levels (scaled to pp).

## Step-by-Step Computation
1. Resolve mode-specific inputs. In stateful mode retrieve lotus-core portfolio and position
   timeseries, convert source rows into normalized valuation points, and preserve source currency
   and FX metadata.
2. Compute daily position weights and return components.
3. Build daily total/local/FX contribution components.
4. Apply smoothing path and NIP/reset zeroing.
5. Aggregate by position for period.
6. Derive period FX contribution as `total - local` and map to response (`*100`).

## Validation and Failure Behavior
- Same endpoint validation/failure semantics as contribution calculation.
- Stateful retrieval or normalization failures block the request rather than falling back to local
  fabricated inputs.
- Stateful `currency_mode=BOTH` requires reporting currency, position currency, and FX rates when
  source position currency differs from the reporting currency.
- If local component is missing/zero, FX contribution absorbs the difference from total.
- In non-FX setups, FX contributions can be zero by construction.

## Configuration Options
- `currency_mode`, `fx`, `hedging`, `report_ccy`
- `smoothing.method`
- `weighting_scheme`
- `stateful_input.metric_basis`, `stateful_input.dimensions`, `stateful_input.include_cash_flows`,
  and `stateful_input.filters` when `input_mode=stateful`

## Outputs
- `results_by_period.<period>.position_contributions[].fx_contribution`
- Hierarchical: `results_by_period.<period>.summary.fx_contribution` and `levels[].rows[].fx_contribution` (when `currency_mode=BOTH`)
- `input_mode`
- `calculation_supportability`, `meta`, `diagnostics`, and `audit`

## Worked Example
Period aggregates for one position:

| quantity | value (decimal) |
|---|---:|
| `C_i` total contribution | 0.0110 |
| `LC_i` local contribution | 0.0080 |
| `FX_i = C_i - LC_i` | 0.0030 |

Response mapping:
- `fx_contribution_pp = 0.0030 * 100 = 0.30`
- `results_by_period.ITD.position_contributions[0].fx_contribution = 0.30`
