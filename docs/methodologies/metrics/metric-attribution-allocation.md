## Metric
Attribution Allocation Effect (`levels[].groups[].allocation`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Request modes:
  - stateless payload (`stateless_input`) with caller-owned attribution inputs
  - legacy stateless top-level attribution inputs
  - stateful payload (`stateful_input`) resolved from lotus-core portfolio, position, benchmark
    assignment, and benchmark component sources
- Modes: `BY_GROUP` and `BY_INSTRUMENT`
- Computed per group, then aggregated to level totals for each resolved period.

## Inputs
- Group-level weights and returns from aligned panel:
  - portfolio weights `w_p`
  - benchmark weights `w_b`
  - benchmark group return `r_base_b`
  - benchmark total return `r_b_total`
- `model` (`BRINSON_FACHLER` or `BRINSON_HOOD_BEEBOWER`)
- `linking`
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`, dimensions, and source
  window fields when source-resolved

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; all aligned portfolio and benchmark group
  facts are supplied by the caller.
- Stateful mode resolves lotus-core portfolio and position timeseries, resolves benchmark
  assignment when needed, and resolves benchmark component inputs through the shared benchmark
  engine sourcing path before normalizing the source rows into the aligned attribution panel.
- `lotus-performance` owns allocation methodology and active-return linking; lotus-core supplies
  source inputs and benchmark/source currency evidence, not allocation conclusions.

## Unit Conventions
- Effect calculations are decimal in engine.
- Response allocation values are percentage points (`*100`).

## Variable Dictionary
- `w_p,g,t`: portfolio BOP weight for group `g`, period bucket `t`
- `w_b,g,t`: benchmark BOP weight for group `g`, period bucket `t`
- `r_b,g,t`: benchmark group return (decimal)
- `r_b,t`: benchmark total return across all groups for period bucket `t`
- `A_g,t`: single-period allocation effect (decimal)
- `A_g`: aggregated allocation effect for group `g` across the requested period
- `AR_geo`: geometric active return across the requested period
- `AR_arith`: arithmetic active return across the requested period
- `scale`: top-down linking factor `AR_geo / AR_arith`
- `M_g`: source metadata for group `g`, including dimensions and benchmark context where available

## Methodology and Formulas
1. Single-period allocation by model:
- Brinson-Fachler:
  - `A_g,t = (w_p,g,t - w_b,g,t) * (r_b,g,t - r_b,t)`
- Brinson-Hood-Beebower:
  - `A_g,t = (w_p,g,t - w_b,g,t) * r_b,g,t`

2. Multi-period linking behavior:
- `linking=NONE`: `A_g = sum_t A_g,t`
- `linking!=NONE`: top-down scaling is applied:
  - `AR_geo = ((prod_t(1 + R_p,t)) - 1) - ((prod_t(1 + R_b,t)) - 1)`
  - `AR_arith = sum_t (R_p,t - R_b,t)`
  - `scale = AR_geo / AR_arith`
  - `A_g = scale * sum_t A_g,t`

## Step-by-Step Computation
1. Resolve mode-specific inputs. In stateful mode retrieve lotus-core portfolio and position
   timeseries, benchmark assignment or explicit benchmark override, and benchmark component inputs,
   then normalize source rows into attribution panel fields.
2. Build aligned portfolio/benchmark panel by date and group.
3. Resample to requested `frequency`, using first `weight_bop` in each bucket and geometric linking for returns.
4. Compute benchmark total return per period bucket `r_b,t`.
5. Compute single-period `allocation` using selected model.
6. If linking enabled, compute `scale` from portfolio and benchmark active return and multiply allocation effects by that factor.
7. Aggregate by hierarchy levels and scale to pp for response.

## Validation and Failure Behavior
- Empty aligned panel produces no period results.
- Invalid model/mode paths return HTTP 400.
- Stateful source resolution fails closed when lotus-core portfolio, position, benchmark, or
  source-currency inputs cannot produce usable attribution panel rows.
- If arithmetic active return is zero in linking path, scaling is skipped (effects unchanged).

## Configuration Options
- `model`
- `linking`
- `group_by`
- `frequency`
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`, dimensions, and source
  window fields when `input_mode=stateful`

## Outputs
- `results_by_period.<period>.levels[].groups[].allocation`
- `results_by_period.<period>.levels[].totals.allocation`
- `results_by_period.<period>.levels[].groups[].total_effect` includes allocation plus selection and interaction
- `benchmark_context` and `calculation_supportability` when source resolution emits bounded
  supportability metadata.

## Worked Example
Brinson-Fachler example:

| input | value |
|---|---:|
| `w_p,g,t` | 0.60 |
| `w_b,g,t` | 0.50 |
| `r_b,g,t` | 0.0400 |
| `r_b,t` | 0.0300 |

- `A_g,t = (0.60 - 0.50) * (0.0400 - 0.0300) = 0.0010`
- Output pp: `0.0010 * 100 = 0.10`

Output mapping:
- `levels[...].groups[...].allocation = 0.10`
