## Metric
Attribution Interaction Effect (`levels[].groups[].interaction`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Modes: `BY_GROUP` and `BY_INSTRUMENT`
- Interaction is computed for both Brinson models using the same formula.

## Inputs
- Group weights: `w_p`, `w_b`
- Group returns: `r_base_p`, `r_base_b`
- `linking`

## Upstream Data Sources
- Request payload only.

## Unit Conventions
- Engine computes interaction in decimal.
- Response interaction values are pp (`*100`).

## Variable Dictionary
- `w_p,g,t`, `w_b,g,t`: portfolio and benchmark BOP weights
- `r_p,g,t`, `r_b,g,t`: portfolio and benchmark group returns (decimal)
- `I_g,t`: single-period interaction effect (decimal)
- `I_g`: aggregated interaction effect for group `g`
- `AR_geo`, `AR_arith`, `scale`: top-down linking definitions used when `linking != NONE`

## Methodology and Formulas
1. Single-period interaction (both models):
- `I_g,t = (w_p,g,t - w_b,g,t) * (r_p,g,t - r_b,g,t)`

2. Linking behavior:
- `NONE`: `I_g = sum_t I_g,t`
- non-`NONE`: `I_g = scale * sum_t I_g,t`, where `scale = AR_geo / AR_arith`

## Step-by-Step Computation
1. Build aligned panel and compute single-period effects.
2. Extract interaction per group-date row.
3. If linking is enabled, compute `scale` from geometric and arithmetic active return and multiply interaction sums by that factor.
4. Aggregate by requested hierarchy levels.
5. Convert to pp in response objects.

## Validation and Failure Behavior
- Empty aligned inputs lead to no period output.
- Invalid mode/model paths return HTTP 400.
- If arithmetic active return is zero, no top-down scaling is applied.

## Configuration Options
- `linking`
- `group_by`, `frequency`
- `model` (does not change interaction formula but affects other effects and totals)

## Outputs
- `results_by_period.<period>.levels[].groups[].interaction`
- `results_by_period.<period>.levels[].totals.interaction`

## Worked Example

| input | value |
|---|---:|
| `w_p,g,t - w_b,g,t` | 0.10 |
| `r_p,g,t - r_b,g,t` | 0.0100 |

- `I_g,t = 0.10 * 0.0100 = 0.0010`
- Output pp: `0.0010 * 100 = 0.10`

Output mapping:
- `levels[...].groups[...].interaction = 0.10`
