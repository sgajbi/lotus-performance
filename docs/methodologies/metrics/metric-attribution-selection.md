# Metric: Attribution Selection Effect

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/attribution`.

## Supported Calculation Modes
- Stateless.

## Upstream Data Sources and Exact Data Points
- Request payload grouped returns.

## Inputs
- Portfolio and benchmark group returns, benchmark weights or portfolio weights depending on model.

## Methodology and Formulas
- Brinson-Fachler: `Selection = w_b * (r_p - r_b)`.
- BHB: `Selection = w_p * (r_p - r_b)`.

## Outputs
- `levels[].groups[].selection` and totals.

## Configuration Options
- `model`, `mode`, `group_by`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- BF: `w_b=0.5`, `r_p=5%`, `r_b=4%` => selection `0.5*1%=0.50%`.



