## Metric
Attribution Total Active Return (`reconciliation.total_active_return`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Request modes:
  - stateless payload (`stateless_input`) with caller-owned portfolio, benchmark, and group inputs
  - legacy stateless top-level attribution inputs
  - stateful payload (`stateful_input`) resolved from lotus-core portfolio, position, benchmark
    assignment, and benchmark component sources
- Modes:
  - `mode=BY_GROUP` (pre-aggregated portfolio groups provided)
  - `mode=BY_INSTRUMENT` (engine builds grouped portfolio panel from instrument valuation series)
- Calculated per resolved period in `results_by_period`.

## Inputs
- `benchmark_groups_data[]` with group/date `weight_bop`, `return_base`
- Portfolio side from either:
  - `portfolio_groups_data[]` (`BY_GROUP`), or
  - `portfolio_data` + `instruments_data[]` (`BY_INSTRUMENT`)
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`,
  `stateful_input.dimensions[]`, and source window fields when source-resolved
- `group_by[]`, `frequency`, `model`, `linking`

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; all required attribution inputs are supplied
  by the caller.
- Stateful mode resolves source input from lotus-core through `CORE_CONTROL_PLANE_BASE_URL`.
  The resolver retrieves portfolio analytics timeseries, position timeseries, benchmark assignment
  when a benchmark override is not supplied, and benchmark component inputs through the shared
  benchmark engine sourcing path. `lotus-performance` then normalizes those source rows into the
  same attribution engine request shape used by stateless execution.
- `lotus-performance` remains the attribution methodology owner; lotus-core supplies portfolio,
  position, benchmark, and source currency inputs, not attribution conclusions.

## Unit Conventions
- Engine computations are decimal returns.
- Response reconciliation values are converted to percentage points (`*100`).

## Variable Dictionary
- `w_p,g,t`: portfolio BOP weight for group `g`, period `t`
- `w_b,g,t`: benchmark BOP weight for group `g`, period `t`
- `r_p,g,t`: portfolio group base return (decimal)
- `r_b,g,t`: benchmark group base return (decimal)
- `r_b,t`: benchmark total return for period `t` (weighted group sum)
- `R_p,t`: portfolio aggregate return per period `t`
- `R_b,t`: benchmark aggregate return per period `t`
- `AR_t`: active return per period `t`
- `AR`: total active return across linked horizon
- `M_g`: source metadata for group `g`, including source dimensions, benchmark context, and
  currency evidence where available

## Methodology and Formulas
1. Per-period aggregate returns:
- `R_p,t = sum_g(w_p,g,t * r_p,g,t)`
- `R_b,t = r_b,t` where `r_b,t = sum_g(w_b,g,t * r_b,g,t)`
- `AR_t = R_p,t - R_b,t`

2. Total active return by linking mode:
- `linking=NONE`: `AR = sum_t AR_t`
- `linking!=NONE`: `AR = (prod_t(1+R_p,t)-1) - (prod_t(1+R_b,t)-1)`
  - if any `R_p,t <= -1` or `R_b,t <= -1`, linked attribution is supportability-invalid and the
    response preserves arithmetic evidence with `linking_invalid_return_chain`.

3. Reconciliation block:
- `total_active_return = 100 * AR`
- `sum_of_effects = allocation + selection + interaction` totals (already scaled to pp)
- `residual = total_active_return - sum_of_effects`

## Step-by-Step Computation
1. Resolve mode-specific inputs. In stateful mode retrieve lotus-core portfolio and position
   timeseries, resolve benchmark assignment or explicit benchmark override, resolve benchmark
   component inputs, and normalize source rows into attribution panel inputs with source metadata.
2. Resolve requested periods and create master request window.
3. Build aligned portfolio/benchmark panel at requested frequency.
4. Compute single-period effects, then aggregate by period slice.
5. Compute portfolio and benchmark per-period aggregate returns.
6. Compute total active return according to `linking` mode.
7. Populate reconciliation fields in response.

## Validation and Failure Behavior
- No resolved periods: HTTP 400.
- Invalid attribution mode: HTTP 400.
- Stateful mode rejects missing or conflicting source/stateless envelopes and fails closed when
  lotus-core portfolio, position, benchmark, or FX/source-currency inputs cannot produce usable
  attribution inputs.
- Source rows without usable dates, weights, market values, group keys, or return fields are not
  guessed into attribution facts.
- Empty aligned panel or empty period slice: period omitted from output.
- Engine/input errors surface as HTTP 400/500 depending on exception type.
- If linked attribution is requested and any portfolio or benchmark period return is less than or
  equal to `-100%`, period `reason_codes` includes `linking_invalid_return_chain` and
  `supportability_evidence.linking_status` is `invalid_return_chain`.

## Configuration Options
- `linking` (`NONE` vs non-`NONE` geometric active return path)
- `frequency` (daily/monthly/quarterly/yearly resampling)
- `mode`, `group_by`, `model`
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`, source dimensions, and
  source window fields when `input_mode=stateful`

## Outputs
- `results_by_period.<period>.reconciliation.total_active_return`
- `results_by_period.<period>.reconciliation.sum_of_effects`
- `results_by_period.<period>.reconciliation.residual`
- Top-level response context remains on `model` and `linking`; those fields are not repeated inside each period result.
- `benchmark_context`, `calculation_supportability`, `meta`, `diagnostics`, and `audit` when
  source resolution emits those supportability blocks.

## Worked Example
Assume two sub-periods:

| t | `R_p,t` | `R_b,t` | `AR_t` |
|---|---:|---:|---:|
| 1 | 0.0200 | 0.0150 | 0.0050 |
| 2 | 0.0100 | 0.0080 | 0.0020 |

- Arithmetic active (`NONE`): `AR = 0.0050 + 0.0020 = 0.0070`
- Geometric active (linked): `AR = (1.02*1.01-1) - (1.015*1.008-1) = 0.00697`

Output mapping (linked case):
- `reconciliation.total_active_return = 0.00697 * 100 = 0.697`
