## Metric
Currency Attribution Local Allocation (`currency_attribution[].effects.local_allocation`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Request modes:
  - stateless attribution inputs with caller-owned local and FX return columns
  - stateful attribution inputs resolved from lotus-core portfolio, position, benchmark, and FX
    source rows when those rows can produce local and FX return fields
- Availability conditions:
  - `currency_mode="BOTH"`
  - aligned effects contain required local/FX columns
  - `group_by` includes `currency`

## Inputs
- Per-currency aggregated series by date:
  - `w_p` (portfolio weight)
  - `w_b` (benchmark weight)
  - `r_local_b` (benchmark local return)
- source currency metadata and FX/local-return fields when `input_mode=stateful`

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; required local and FX fields are supplied by
  the caller.
- Stateful mode uses lotus-core portfolio and position timeseries, benchmark assignment/component
  inputs, and FX/source currency evidence normalized by the attribution resolver. The currency
  attribution branch runs only after those source rows produce the required local and FX columns.
- `lotus-performance` owns Karnosky-Singer local allocation methodology; lotus-core supplies source
  rows and currency evidence, not currency-attribution conclusions.

## Unit Conventions
- Engine computes in decimal.
- Response local allocation is scaled to percentage points (`*100`).

## Variable Dictionary
- `w_p,c,t`: portfolio weight for currency `c` at period `t`
- `w_b,c,t`: benchmark weight for currency `c` at period `t`
- `r_local_b,c,t`: benchmark local return (decimal)
- `LA_c,t`: local allocation effect (decimal)
- `LA_c`: aggregated local allocation effect for currency `c`
- `TE_c`: per-currency total effect in decimal

## Methodology and Formulas
- Karnosky-Singer local allocation (implemented formula):
- `LA_c,t = (w_p,c,t - w_b,c,t) * r_local_b,c,t`

Period/currency aggregation in response:
- `LA_c = sum_t LA_c,t`
- Response field value: `100 * LA_c`
- `TE_c = LA_c + LS_c + CA_c + CS_c`

## Step-by-Step Computation
1. Resolve mode-specific attribution inputs. In stateful mode retrieve and normalize lotus-core
   portfolio, position, benchmark, and FX/source currency rows.
2. Build daily attribution panel and aggregate by (`date`, `currency`).
3. Compute `LA_c,t` for each currency/date row.
4. Sum across dates per currency.
5. Convert to pp and populate `currency_attribution[].effects.local_allocation`.

## Validation and Failure Behavior
- If currency attribution prerequisites are missing (required columns or currency key), `currency_attribution` block is omitted.
- Stateful source rows without usable source currency, reporting currency, local return, or FX
  return evidence do not produce currency-attribution facts.
- Invalid attribution request/mode handling follows endpoint-level HTTP 400/500 behavior.

## Configuration Options
- `currency_mode` must be `BOTH`.
- `frequency` controls period bucketing before currency-effect aggregation.
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`, source dimensions, and
  source window fields when `input_mode=stateful`

## Outputs
- `results_by_period.<period>.currency_attribution[].effects.local_allocation`
- contributes to `results_by_period.<period>.currency_attribution[].effects.total_effect`
- `calculation_supportability` when source resolution emits bounded supportability metadata.

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
