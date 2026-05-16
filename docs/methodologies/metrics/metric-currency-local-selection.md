## Metric
Currency Attribution Local Selection (`currency_attribution[].effects.local_selection`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Request modes:
  - stateless attribution inputs with caller-owned local and FX return columns
  - stateful attribution inputs resolved from lotus-core portfolio, position, benchmark, and FX
    source rows when those rows can produce local and FX return fields
- Availability requires currency attribution path to be active:
  - `currency_mode=BOTH`
  - required columns are present in the aligned effects panel
  - `group_by` includes the `currency` dimension

## Inputs
- `w_b` (benchmark currency weight)
- `r_local_p` (portfolio local return by currency)
- `r_local_b` (benchmark local return by currency)
- source currency metadata and FX/local-return fields when `input_mode=stateful`

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; required local and FX fields are supplied by
  the caller.
- Stateful mode uses lotus-core portfolio and position timeseries, benchmark assignment/component
  inputs, and FX/source currency evidence normalized by the attribution resolver. The currency
  attribution branch runs only after those source rows produce the required local and FX columns.
- `lotus-performance` owns Karnosky-Singer local selection methodology; lotus-core supplies source
  rows and currency evidence, not currency-attribution conclusions.

## Unit Conventions
- Formula computed in decimal.
- Response value is percentage points (`*100`).

## Variable Dictionary
- `w_b,c,t`: benchmark weight for currency `c`, period `t`
- `r_local_p,c,t`: portfolio local return (decimal)
- `r_local_b,c,t`: benchmark local return (decimal)
- `LS_c,t`: local selection effect (decimal)
- `LS_c`: aggregated local selection effect for currency `c`
- `TE_c`: per-currency total effect in decimal

## Methodology and Formulas
- Karnosky-Singer local selection:
- `LS_c,t = w_b,c,t * (r_local_p,c,t - r_local_b,c,t)`

Aggregation:
- `LS_c = sum_t LS_c,t`
- response field = `100 * LS_c`
- `TE_c = LA_c + LS_c + CA_c + CS_c`
- If the request groups by `currency` plus additional dimensions, the engine first recomputes a
  date/currency panel by summing portfolio and benchmark weights and calculating portfolio and
  benchmark local returns as weight-averaged returns. It does not sum granular local returns across
  sectors or other visible rows.

## Step-by-Step Computation
1. Resolve mode-specific attribution inputs. In stateful mode retrieve and normalize lotus-core
   portfolio, position, benchmark, and FX/source currency rows.
2. Aggregate aligned panel by (`date`, `currency`).
3. Compute local return spread per row.
4. Multiply by benchmark weight to get `LS_c,t`.
5. Sum across dates and convert to pp in response.

## Validation and Failure Behavior
- Currency-attribution block is omitted when prerequisites are not met.
- Stateful source rows without usable source currency, reporting currency, local return, or FX
  return evidence do not produce currency-attribution facts.
- Endpoint-level invalid input errors map to HTTP 400/500 paths.

## Configuration Options
- `currency_mode=BOTH`
- `frequency` (controls aggregation horizon)
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`, source dimensions, and
  source window fields when `input_mode=stateful`

## Outputs
- `results_by_period.<period>.currency_attribution[].effects.local_selection`
- contributes to `results_by_period.<period>.currency_attribution[].effects.total_effect`
- `calculation_supportability` when source resolution emits bounded supportability metadata.

## Worked Example

| quantity | formula | value |
|---|---|---:|
| Local spread | `r_local_p - r_local_b` | `0.0250 - 0.0200 = 0.0050` |
| Weighted local selection | `w_b * spread` | `0.50 * 0.0050 = 0.0025` |
| Response pp | `0.0025 * 100` | 0.25 |

Output mapping:
- `currency_attribution[<ccy>].effects.local_selection = 0.25`
