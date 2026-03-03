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
- `r_p`: portfolio group return (decimal)
- `r_b`: benchmark group return (decimal)
- `w_p`, `w_b`: portfolio/benchmark BOP weights
- `S`: selection effect (decimal)

## Methodology and Formulas
1. Single-period selection by model:
- Brinson-Fachler:
  - `S = w_b * (r_p - r_b)`
- Brinson-Hood-Beebower:
  - `S = w_p * (r_p - r_b)`

2. Linking behavior:
- `NONE`: arithmetic summation over periods.
- non-`NONE`: top-down scaling by `geometric_active/arithmetic_active`.

## Step-by-Step Computation
1. Align portfolio and benchmark panels.
2. Compute single-period selection per group from chosen model.
3. Apply optional top-down scaling for linked output.
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
| `w_b` | 0.50 |
| `r_p` | 0.0500 |
| `r_b` | 0.0400 |

- `S = 0.50 * (0.0500 - 0.0400) = 0.0050`
- Output pp: `0.0050 * 100 = 0.50`

Output mapping:
- `levels[...].groups[...].selection = 0.50`
