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
- `w_p`, `w_b`: portfolio and benchmark BOP weights
- `r_p`, `r_b`: portfolio and benchmark group returns (decimal)
- `I`: interaction effect (decimal)

## Methodology and Formulas
1. Single-period interaction (both models):
- `I = (w_p - w_b) * (r_p - r_b)`

2. Linking behavior:
- `NONE`: arithmetic sum across periods.
- non-`NONE`: top-down scaling by `geometric_active/arithmetic_active`.

## Step-by-Step Computation
1. Build aligned panel and compute single-period effects.
2. Extract interaction per group-date row.
3. Apply linking scaling if enabled.
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
| `w_p - w_b` | 0.10 |
| `r_p - r_b` | 0.0100 |

- `I = 0.10 * 0.0100 = 0.0010`
- Output pp: `0.0010 * 100 = 0.10`

Output mapping:
- `levels[...].groups[...].interaction = 0.10`
