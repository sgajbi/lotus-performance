## Metric
Attribution Selection Effect (`levels[].groups[].selection`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
- Modes: `BY_GROUP` and `BY_INSTRUMENT`
- Computed at group-period level then aggregated by hierarchy and period.

## Inputs
- Group-level returns:
  - portfolio base return `r_base_p`
  - benchmark base return `r_base_b`
- Group-level weights (`w_p`, `w_b`)
- `model`, `linking`

## Upstream Data Sources
- Request payload only.

## Unit Conventions
- Selection effect is computed in decimal and returned in pp (`*100`).

## Variable Dictionary
- `r_p,g,t`: portfolio group return (decimal)
- `r_b,g,t`: benchmark group return (decimal)
- `w_p,g,t`, `w_b,g,t`: portfolio/benchmark BOP weights
- `S_g,t`: single-period selection effect (decimal)
- `S_g`: aggregated selection effect for group `g`
- `AR_geo`, `AR_arith`, `scale`: same linking definitions used by allocation and interaction docs

## Methodology and Formulas
1. Single-period selection by model:
- Brinson-Fachler:
  - `S_g,t = w_b,g,t * (r_p,g,t - r_b,g,t)`
- Brinson-Hood-Beebower:
  - `S_g,t = w_p,g,t * (r_p,g,t - r_b,g,t)`

2. Linking behavior:
- `NONE`: `S_g = sum_t S_g,t`
- non-`NONE`: `S_g = scale * sum_t S_g,t`, where `scale = AR_geo / AR_arith`

## Step-by-Step Computation
1. Align portfolio and benchmark panels by group and resample to requested `frequency`.
2. Compute single-period selection per group from the chosen model.
3. If linking is enabled, compute `scale` from geometric and arithmetic active return and multiply the arithmetic selection sums by that factor.
4. Aggregate by requested levels.
5. Convert to pp for response.

## Validation and Failure Behavior
- Empty aligned panel yields no period output.
- Invalid request mode/model handled as HTTP 400.
- If arithmetic active return is zero, linking scaler is not applied.

## Configuration Options
- `model`
- `linking`
- `group_by`, `frequency`

## Outputs
- `results_by_period.<period>.levels[].groups[].selection`
- `results_by_period.<period>.levels[].totals.selection`

## Worked Example
Brinson-Fachler example:

| input | value |
|---|---:|
| `w_b,g,t` | 0.50 |
| `r_p,g,t` | 0.0500 |
| `r_b,g,t` | 0.0400 |

- `S_g,t = 0.50 * (0.0500 - 0.0400) = 0.0050`
- Output pp: `0.0050 * 100 = 0.50`

Output mapping:
- `levels[...].groups[...].selection = 0.50`
