## Metric
Currency Attribution Currency Selection (`currency_attribution[].effects.currency_selection`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Request modes:
  - stateless attribution inputs with caller-owned local and FX return columns
  - stateful attribution inputs resolved from lotus-core portfolio, position, benchmark, and FX
    source rows when those rows can produce local and FX return fields
- Available only when currency-attribution branch is active:
  - `currency_mode=BOTH`
  - required local/FX columns are present in the aligned effects panel
  - `group_by` includes the `currency` key so the engine can aggregate by currency

## Inputs
- `w_b`
- `r_local_p`, `r_local_b`
- `r_fx_b`
- source currency metadata and FX/local-return fields when `input_mode=stateful`

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; required local and FX fields are supplied by
  the caller.
- Stateful mode uses lotus-core portfolio and position timeseries, benchmark assignment/component
  inputs, and FX/source currency evidence normalized by the attribution resolver. The currency
  attribution branch runs only after those source rows produce the required local and FX columns.
- `lotus-performance` owns Karnosky-Singer currency selection methodology; lotus-core supplies
  source rows and currency evidence, not currency-attribution conclusions.

## Unit Conventions
- Computed in decimal, emitted as percentage points (`*100`).

## Variable Dictionary
- `w_b,c,t`: benchmark weight
- `r_local_p,c,t`: portfolio local return
- `r_local_b,c,t`: benchmark local return
- `r_fx_b,c,t`: benchmark FX return
- `CS_c,t`: currency selection effect (decimal)
- `CS_c`: aggregated currency selection effect for currency `c`
- `TE_c`: per-currency total effect in decimal

## Methodology and Formulas
- Implemented formula:
- `CS_c,t = w_b,c,t * (r_local_p,c,t - r_local_b,c,t) * r_fx_b,c,t`

Aggregation and total effect:
- `CS_c = sum_t CS_c,t`
- response field = `100 * CS_c`
- per-currency `total_effect` is sum of four currency effects:
  - `TE_c = LA_c + LS_c + CA_c + CS_c`

## Step-by-Step Computation
1. Resolve mode-specific attribution inputs. In stateful mode retrieve and normalize lotus-core
   portfolio, position, benchmark, and FX/source currency rows.
2. Compute local return spread per currency-date.
3. Multiply by benchmark weight.
4. Multiply by benchmark FX return.
5. Sum across dates and convert to pp.
6. Add into per-currency total effect.

## Validation and Failure Behavior
- Currency attribution omitted if prerequisites are not met.
- Stateful source rows without usable source currency, reporting currency, local return, or FX
  return evidence do not produce currency-attribution facts.
- Standard endpoint error behavior applies for invalid inputs/exceptions.

## Configuration Options
- `currency_mode=BOTH`
- `frequency`
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`, source dimensions, and
  source window fields when `input_mode=stateful`

## Outputs
- `results_by_period.<period>.currency_attribution[].effects.currency_selection`
- contributes to `results_by_period.<period>.currency_attribution[].effects.total_effect`
- `calculation_supportability` when source resolution emits bounded supportability metadata.

## Worked Example

| quantity | formula | value |
|---|---|---:|
| Local spread | `r_local_p - r_local_b` | `0.0250 - 0.0200 = 0.0050` |
| Weighted spread | `w_b * spread` | `0.50 * 0.0050 = 0.0025` |
| Currency selection (decimal) | `weighted_spread * r_fx_b` | `0.0025 * 0.0100 = 0.000025` |
| Response pp | `0.000025 * 100` | 0.0025 |

Output mapping:
- `currency_attribution[<ccy>].effects.currency_selection = 0.0025`
