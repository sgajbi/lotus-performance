## Metric
Attribution Allocation Effect (`levels[].groups[].allocation`)

## Endpoint and Mode Coverage
- Endpoint: `POST /performance/attribution`
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

## Upstream Data Sources
- Request payload only.

## Unit Conventions
- Effect calculations are decimal in engine.
- Response allocation values are percentage points (`*100`).

## Variable Dictionary
- `w_p`, `w_b`: portfolio/benchmark BOP weights by group and period
- `r_b`: benchmark group return (decimal)
- `r_b_total`: benchmark total return (decimal)
- `A`: allocation effect (decimal)

## Methodology and Formulas
1. Single-period allocation by model:
- Brinson-Fachler:
  - `A = (w_p - w_b) * (r_b - r_b_total)`
- Brinson-Hood-Beebower:
  - `A = (w_p - w_b) * r_b`

2. Multi-period linking behavior:
- `linking=NONE`: sum arithmetic effects across periods.
- `linking!=NONE`: top-down scaling is applied:
  - `scale = geometric_active_return / arithmetic_active_return`
  - linked allocation effect = arithmetic allocation effect * `scale`

## Step-by-Step Computation
1. Build aligned portfolio/benchmark panel by date and group.
2. Compute benchmark total return per date (`r_b_total`).
3. Compute single-period `allocation` using selected model.
4. If linking enabled, scale effects using top-down factor.
5. Aggregate by hierarchy levels and scale to pp for response.

## Validation and Failure Behavior
- Empty aligned panel produces no period results.
- Invalid model/mode paths return HTTP 400.
- If arithmetic active return is zero in linking path, scaling is skipped (effects unchanged).

## Configuration Options
- `model`
- `linking`
- `group_by`
- `frequency`

## Outputs
- `results_by_period.<period>.levels[].groups[].allocation`
- `results_by_period.<period>.levels[].totals.allocation`

## Worked Example
Brinson-Fachler example:

| input | value |
|---|---:|
| `w_p` | 0.60 |
| `w_b` | 0.50 |
| `r_b` | 0.0400 |
| `r_b_total` | 0.0300 |

- `A = (0.60 - 0.50) * (0.0400 - 0.0300) = 0.0010`
- Output pp: `0.0010 * 100 = 0.10`

Output mapping:
- `levels[...].groups[...].allocation = 0.10`
