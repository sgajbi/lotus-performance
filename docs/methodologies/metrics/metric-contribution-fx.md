## Metric
Position FX Contribution (`position_contributions[].fx_contribution`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/contribution`
- Mode: stateless request
- FX contribution is decomposition residual between total and local contribution in period aggregation.

## Inputs
- Position daily total contribution components
- Position daily local contribution components
- `currency_mode`, `fx`, `hedging`, `report_ccy`
- `smoothing.method`

## Upstream Data Sources
- Request payload only.

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
1. Compute daily position weights and return components.
2. Build daily total/local/FX contribution components.
3. Apply smoothing path and NIP/reset zeroing.
4. Aggregate by position for period.
5. Derive period FX contribution as `total - local` and map to response (`*100`).

## Validation and Failure Behavior
- Same endpoint validation/failure semantics as contribution calculation.
- If local component is missing/zero, FX contribution absorbs the difference from total.
- In non-FX setups, FX contributions can be zero by construction.

## Configuration Options
- `currency_mode`, `fx`, `hedging`, `report_ccy`
- `smoothing.method`
- `weighting_scheme`

## Outputs
- `results_by_period.<period>.position_contributions[].fx_contribution`
- Hierarchical: `results_by_period.<period>.summary.fx_contribution` and `levels[].rows[].fx_contribution` (when `currency_mode=BOTH`)

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
