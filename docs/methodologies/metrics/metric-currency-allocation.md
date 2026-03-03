## Metric
Currency Attribution Currency Allocation (`currency_attribution[].effects.currency_allocation`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Available only in currency attribution path (`currency_mode=BOTH` + required fields + `currency` key).

## Inputs
- `w_p`, `w_b`
- `r_local_b`
- `r_fx_b` (benchmark FX return by currency)

## Upstream Data Sources
- Request payload only.

## Unit Conventions
- Engine computes decimal effect.
- Response is percentage points (`*100`).

## Variable Dictionary
- `w_p,c,t`, `w_b,c,t`: portfolio/benchmark weights
- `r_local_b,c,t`: benchmark local return (decimal)
- `r_fx_b,c,t`: benchmark FX return (decimal)
- `CA_c,t`: currency allocation effect (decimal)

## Methodology and Formulas
- Implemented formula:
- `CA_c,t = (w_p,c,t - w_b,c,t) * (1 + r_local_b,c,t) * r_fx_b,c,t`

Aggregation:
- `CA_c = sum_t CA_c,t`
- response field = `100 * CA_c`

## Step-by-Step Computation
1. Build currency-level panel by date.
2. Compute weight active term `(w_p - w_b)`.
3. Compute local-growth term `(1 + r_local_b)`.
4. Multiply with benchmark FX return to get `CA_c,t`.
5. Sum over dates and scale to pp.

## Validation and Failure Behavior
- If currency effects cannot be computed (missing required columns), field is absent with entire currency-attribution block.
- Endpoint handles invalid requests/errors as HTTP 400/500.

## Configuration Options
- `currency_mode=BOTH`
- `frequency`

## Outputs
- `results_by_period.<period>.currency_attribution[].effects.currency_allocation`

## Worked Example

| quantity | formula | value |
|---|---|---:|
| Active weight | `w_p - w_b` | `0.55 - 0.50 = 0.05` |
| Local growth | `1 + r_local_b` | `1 + 0.0200 = 1.0200` |
| Currency allocation (decimal) | `active_weight * local_growth * r_fx_b` | `0.05 * 1.0200 * 0.0100 = 0.00051` |
| Response pp | `0.00051 * 100` | 0.051 |

Output mapping:
- `currency_attribution[<ccy>].effects.currency_allocation = 0.051`
