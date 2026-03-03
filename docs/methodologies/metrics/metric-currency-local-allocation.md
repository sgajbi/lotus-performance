## Metric
Currency Attribution Local Allocation (`currency_attribution[].effects.local_allocation`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Availability conditions:
  - `currency_mode="BOTH"`
  - aligned effects contain required local/FX columns
  - grouped data includes `currency` key

## Inputs
- Per-currency aggregated series by date:
  - `w_p` (portfolio weight)
  - `w_b` (benchmark weight)
  - `r_local_b` (benchmark local return)

## Upstream Data Sources
- Request payload only.

## Unit Conventions
- Engine computes in decimal.
- Response local allocation is scaled to percentage points (`*100`).

## Variable Dictionary
- `w_p,c,t`: portfolio weight for currency `c` at period `t`
- `w_b,c,t`: benchmark weight for currency `c` at period `t`
- `r_local_b,c,t`: benchmark local return (decimal)
- `LA_c,t`: local allocation effect (decimal)

## Methodology and Formulas
- Karnosky-Singer local allocation (implemented formula):
- `LA_c,t = (w_p,c,t - w_b,c,t) * r_local_b,c,t`

Period/currency aggregation in response:
- `LA_c = sum_t LA_c,t`
- Response field value: `100 * LA_c`

## Step-by-Step Computation
1. Build daily attribution panel and aggregate by (`date`, `currency`).
2. Compute `LA_c,t` for each currency/date row.
3. Sum across dates per currency.
4. Convert to pp and populate `currency_attribution[].effects.local_allocation`.

## Validation and Failure Behavior
- If currency attribution prerequisites are missing (required columns or currency key), `currency_attribution` block is omitted.
- Invalid attribution request/mode handling follows endpoint-level HTTP 400/500 behavior.

## Configuration Options
- `currency_mode` must be `BOTH`.
- `frequency` controls period bucketing before currency-effect aggregation.

## Outputs
- `results_by_period.<period>.currency_attribution[].effects.local_allocation`

## Worked Example

| input | value |
|---|---:|
| `w_p` | 0.55 |
| `w_b` | 0.50 |
| `r_local_b` | 0.0200 |

- `LA = (0.55 - 0.50) * 0.0200 = 0.0010`
- Output pp: `0.0010 * 100 = 0.10`

Output mapping:
- `currency_attribution[<ccy>].effects.local_allocation = 0.10`
