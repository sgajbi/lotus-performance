# Metric: Currency Attribution Currency Allocation

## Quantitative Conventions
- Unless explicitly noted otherwise, endpoint-level performance and attribution outputs are expressed in **percentage points**.
- `returns/series` payload values are expressed in **decimal return form** (`0.0012 = 12 bps`).
- Geometric linking uses `Π(1+r_t)-1`.
- Annualization uses the configured day-count basis and annualization factor.

## Lotus-Performance Endpoint(s)
- `POST /performance/attribution` with `currency_mode=BOTH`.

## Supported Calculation Modes
- Stateless.

## Upstream Data Sources and Exact Data Points
- Request currency benchmark return components.

## Inputs
- `w_p`, `w_b`, `r_local_b`, `r_fx_b`.

## Methodology and Formulas
- Currency allocation: `(w_p - w_b) * (1 + r_local_b) * r_fx_b`.

## Outputs
- `currency_attribution[].effects.currency_allocation`.

## Configuration Options
- `currency_mode=BOTH`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- `w diff=0.05`, `r_local_b=2%`, `r_fx_b=1%` => `0.05*1.02*0.01=0.051%`.



