## Metric
Currency Attribution Currency Selection (`currency_attribution[].effects.currency_selection`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Available only when currency-attribution branch is active (`currency_mode=BOTH` and required data present).

## Inputs
- `w_b`
- `r_local_p`, `r_local_b`
- `r_fx_b`

## Upstream Data Sources
- Request payload only.

## Unit Conventions
- Computed in decimal, emitted as percentage points (`*100`).

## Variable Dictionary
- `w_b,c,t`: benchmark weight
- `r_local_p,c,t`: portfolio local return
- `r_local_b,c,t`: benchmark local return
- `r_fx_b,c,t`: benchmark FX return
- `CS_c,t`: currency selection effect (decimal)

## Methodology and Formulas
- Implemented formula:
- `CS_c,t = w_b,c,t * (r_local_p,c,t - r_local_b,c,t) * r_fx_b,c,t`

Aggregation and total effect:
- `CS_c = sum_t CS_c,t`
- response field = `100 * CS_c`
- per-currency `total_effect` is sum of four currency effects:
  - `local_allocation + local_selection + currency_allocation + currency_selection`

## Step-by-Step Computation
1. Compute local return spread per currency-date.
2. Multiply by benchmark weight.
3. Multiply by benchmark FX return.
4. Sum across dates and convert to pp.
5. Add into per-currency total effect.

## Validation and Failure Behavior
- Currency attribution omitted if prerequisites are not met.
- Standard endpoint error behavior applies for invalid inputs/exceptions.

## Configuration Options
- `currency_mode=BOTH`
- `frequency`

## Outputs
- `results_by_period.<period>.currency_attribution[].effects.currency_selection`
- contributes to `results_by_period.<period>.currency_attribution[].effects.total_effect`

## Worked Example

| quantity | formula | value |
|---|---|---:|
| Local spread | `r_local_p - r_local_b` | `0.0250 - 0.0200 = 0.0050` |
| Weighted spread | `w_b * spread` | `0.50 * 0.0050 = 0.0025` |
| Currency selection (decimal) | `weighted_spread * r_fx_b` | `0.0025 * 0.0100 = 0.000025` |
| Response pp | `0.000025 * 100` | 0.0025 |

Output mapping:
- `currency_attribution[<ccy>].effects.currency_selection = 0.0025`
