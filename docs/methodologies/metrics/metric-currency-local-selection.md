## Metric
Currency Attribution Local Selection (`currency_attribution[].effects.local_selection`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Availability requires currency attribution path to be active (`currency_mode=BOTH`, required columns present, `currency` dimension available).

## Inputs
- `w_b` (benchmark currency weight)
- `r_local_p` (portfolio local return by currency)
- `r_local_b` (benchmark local return by currency)

## Upstream Data Sources
- Request payload only.

## Unit Conventions
- Formula computed in decimal.
- Response value is percentage points (`*100`).

## Variable Dictionary
- `w_b,c,t`: benchmark weight for currency `c`, period `t`
- `r_local_p,c,t`: portfolio local return (decimal)
- `r_local_b,c,t`: benchmark local return (decimal)
- `LS_c,t`: local selection effect (decimal)

## Methodology and Formulas
- Karnosky-Singer local selection:
- `LS_c,t = w_b,c,t * (r_local_p,c,t - r_local_b,c,t)`

Aggregation:
- `LS_c = sum_t LS_c,t`
- response field = `100 * LS_c`

## Step-by-Step Computation
1. Aggregate aligned panel by (`date`, `currency`).
2. Compute local return spread per row.
3. Multiply by benchmark weight to get `LS_c,t`.
4. Sum across dates and convert to pp in response.

## Validation and Failure Behavior
- Currency-attribution block is omitted when prerequisites are not met.
- Endpoint-level invalid input errors map to HTTP 400/500 paths.

## Configuration Options
- `currency_mode=BOTH`
- `frequency` (controls aggregation horizon)

## Outputs
- `results_by_period.<period>.currency_attribution[].effects.local_selection`

## Worked Example

| quantity | formula | value |
|---|---|---:|
| Local spread | `r_local_p - r_local_b` | `0.0250 - 0.0200 = 0.0050` |
| Weighted local selection | `w_b * spread` | `0.50 * 0.0050 = 0.0025` |
| Response pp | `0.0025 * 100` | 0.25 |

Output mapping:
- `currency_attribution[<ccy>].effects.local_selection = 0.25`
