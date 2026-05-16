## Metric
Currency Attribution Currency Allocation (`currency_attribution[].effects.currency_allocation`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Request modes:
  - stateless attribution inputs with caller-owned local and FX return columns
  - stateful attribution inputs resolved from lotus-core portfolio, position, benchmark, and FX
    source rows when those rows can produce local and FX return fields
- Available only in currency attribution path:
  - `currency_mode=BOTH`
  - required local/FX columns are present in the aligned effects panel
  - `group_by` includes the `currency` key so the engine can aggregate by currency

## Inputs
- `w_p`, `w_b`
- `r_local_b`
- `r_fx_b` (benchmark FX return by currency)
- source currency metadata and FX/local-return fields when `input_mode=stateful`

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; required local and FX fields are supplied by
  the caller.
- Stateful mode uses lotus-core portfolio and position timeseries, benchmark assignment/component
  inputs, and FX/source currency evidence normalized by the attribution resolver. The currency
  attribution branch runs only after those source rows produce the required local and FX columns.
- `lotus-performance` owns Karnosky-Singer currency allocation methodology; lotus-core supplies
  source rows and currency evidence, not currency-attribution conclusions.

## Unit Conventions
- Engine computes decimal effect.
- Response is percentage points (`*100`).

## Variable Dictionary
- `w_p,c,t`, `w_b,c,t`: portfolio/benchmark weights
- `r_local_b,c,t`: benchmark local return (decimal)
- `r_fx_b,c,t`: benchmark FX return (decimal)
- `CA_c,t`: currency allocation effect (decimal)
- `CA_c`: aggregated currency allocation effect for currency `c`
- `TE_c`: per-currency total effect in decimal

## Methodology and Formulas
- Implemented formula:
- `CA_c,t = (w_p,c,t - w_b,c,t) * (1 + r_local_b,c,t) * r_fx_b,c,t`

Aggregation:
- `CA_c = sum_t CA_c,t`
- response field = `100 * CA_c`
- `TE_c = LA_c + LS_c + CA_c + CS_c`
- If the request groups by `currency` plus additional dimensions, the engine first recomputes a
  date/currency panel by summing portfolio and benchmark weights and calculating benchmark local
  and FX returns as weight-averaged returns. It does not sum granular local or FX returns across
  sectors or other visible rows.

## Step-by-Step Computation
1. Resolve mode-specific attribution inputs. In stateful mode retrieve and normalize lotus-core
   portfolio, position, benchmark, and FX/source currency rows.
2. Build currency-level panel by date.
3. Compute weight active term `(w_p - w_b)`.
4. Compute local-growth term `(1 + r_local_b)`.
5. Multiply with benchmark FX return to get `CA_c,t`.
6. Sum over dates and scale to pp.

## Validation and Failure Behavior
- If currency effects cannot be computed (missing required columns), field is absent with entire currency-attribution block.
- Stateful source rows without usable source currency, reporting currency, local return, or FX
  return evidence do not produce currency-attribution facts.
- Endpoint handles invalid requests/errors as HTTP 400/500.

## Configuration Options
- `currency_mode=BOTH`
- `frequency`
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`, source dimensions, and
  source window fields when `input_mode=stateful`

## Outputs
- `results_by_period.<period>.currency_attribution[].effects.currency_allocation`
- contributes to `results_by_period.<period>.currency_attribution[].effects.total_effect`
- `calculation_supportability` when source resolution emits bounded supportability metadata.

## Worked Example

| quantity | formula | value |
|---|---|---:|
| Active weight | `w_p - w_b` | `0.55 - 0.50 = 0.05` |
| Local growth | `1 + r_local_b` | `1 + 0.0200 = 1.0200` |
| Currency allocation (decimal) | `active_weight * local_growth * r_fx_b` | `0.05 * 1.0200 * 0.0100 = 0.00051` |
| Response pp | `0.00051 * 100` | 0.051 |

Output mapping:
- `currency_attribution[<ccy>].effects.currency_allocation = 0.051`
