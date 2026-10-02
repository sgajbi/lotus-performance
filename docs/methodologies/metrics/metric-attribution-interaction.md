## Metric
Attribution Interaction Effect (`levels[].groups[].interaction`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Request modes:
  - stateless payload (`stateless_input`) with caller-owned attribution inputs
  - legacy stateless top-level attribution inputs
  - stateful payload (`stateful_input`) resolved from lotus-core portfolio, position, benchmark
    assignment, and benchmark component sources
- Modes: `BY_GROUP` and `BY_INSTRUMENT`
- Brinson-Fachler reports a separate interaction effect. Brinson-Hood-Beebower reports interaction
  as zero because its portfolio-weighted selection already includes that interaction.

## Inputs
- Group weights: `w_p`, `w_b`
- Group returns: `r_base_p`, `r_base_b`
- `linking`
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`, dimensions, and source
  window fields when source-resolved

## Upstream Data Sources
- Stateless mode has no runtime upstream dependency; all portfolio and benchmark weights and
  returns are supplied by the caller.
- Stateful mode resolves lotus-core portfolio and position timeseries, benchmark assignment or
  explicit benchmark override, and benchmark component inputs through the shared benchmark engine
  sourcing path before normalizing them into aligned attribution panel inputs.
- `lotus-performance` owns interaction methodology and linking; lotus-core supplies source inputs,
  benchmark inputs, and source currency evidence, not interaction conclusions.

## Unit Conventions
- Engine computes interaction in decimal.
- Response interaction values are pp (`*100`).

## Variable Dictionary
- `w_p,g,t`, `w_b,g,t`: portfolio and benchmark BOP weights
- `r_p,g,t`, `r_b,g,t`: portfolio and benchmark group returns (decimal)
- `I_g,t`: single-period interaction effect (decimal)
- `I_g`: aggregated interaction effect for group `g`
- `AR_geo`, `AR_arith`, `scale`: top-down linking definitions used when `linking != NONE`
- `M_g`: source metadata for group `g`, including dimensions, benchmark context, and currency
  evidence where available

## Methodology and Formulas
1. Single-period interaction by model:
- Brinson-Fachler:
  - `I_g,t = (w_p,g,t - w_b,g,t) * (r_p,g,t - r_b,g,t)`
- Brinson-Hood-Beebower:
  - `I_g,t = 0`; the portfolio-weighted selection term is the combined selection effect and already
    contains the interaction contribution.

2. Linking behavior:
- `NONE`: `I_g = sum_t I_g,t`
- non-`NONE`: `I_g = scale * sum_t I_g,t`, where `scale = AR_geo / AR_arith`; if any portfolio
  or benchmark period return is less than or equal to `-100%`, the linked chain is
  supportability-invalid and interaction is not presented as clean linked attribution.

## Step-by-Step Computation
1. Resolve mode-specific inputs. In stateful mode retrieve lotus-core portfolio and position
   timeseries, resolve benchmark assignment or explicit benchmark override, resolve benchmark
   component inputs, and normalize source rows into attribution panel fields.
2. Build aligned panel and compute single-period effects.
3. Calculate the separate Brinson-Fachler interaction or the explicit zero BHB interaction per
   group-date row.
4. If linking is enabled, compute `scale` from geometric and arithmetic active return and multiply interaction sums by that factor.
5. Aggregate by requested hierarchy levels.
6. Convert to pp in response objects.

## Validation and Failure Behavior
- Empty aligned inputs lead to no period output.
- Invalid mode/model paths return HTTP 400.
- Stateful source resolution fails closed when lotus-core portfolio, position, benchmark, or
  source-currency inputs cannot produce usable attribution panel rows.
- If arithmetic active return is zero or ill-conditioned relative to summed absolute daily active
  returns, no top-down scaling is applied and `linking_scaling_skipped` is emitted. The threshold is
  `sqrt(float64 epsilon) * sum_t abs(AR_t)`.
- If a linked period contains a portfolio or benchmark return less than or equal to `-100%`, the
  period emits `linking_invalid_return_chain` and
  `supportability_evidence.linking_status="invalid_return_chain"`.

## Configuration Options
- `linking`
- `group_by`, `frequency`
- `model` (BF reports the three-effect decomposition; BHB reports a two-effect decomposition with
  zero separate interaction)
- `stateful_input.portfolio_id`, optional `stateful_input.benchmark_id`, dimensions, and source
  window fields when `input_mode=stateful`

## Outputs
- `results_by_period.<period>.levels[].groups[].interaction`
- `results_by_period.<period>.levels[].totals.interaction`
- `benchmark_context` and `calculation_supportability` when source resolution emits bounded
  supportability metadata.

## Worked Example

| input | value |
|---|---:|
| `w_p,g,t - w_b,g,t` | 0.10 |
| `r_p,g,t - r_b,g,t` | 0.0100 |

- `I_g,t = 0.10 * 0.0100 = 0.0010`
- Output pp: `0.0010 * 100 = 0.10`

This worked formula is the Brinson-Fachler result. Under BHB the response maps the same field to
`0.00` pp because the portfolio-weighted selection term carries the combined effect.

Output mapping:
- `levels[...].groups[...].interaction = 0.10`
