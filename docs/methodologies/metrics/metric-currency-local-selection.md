# Metric: Currency Attribution Local Selection

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
- Request local return series by currency.

## Inputs
- `w_b`, `r_local_p`, `r_local_b`.

## Methodology and Formulas
- Local selection: `w_b * (r_local_p - r_local_b)`.

## Outputs
- `currency_attribution[].effects.local_selection`.

## Configuration Options
- `currency_mode=BOTH`.

## Assumptions and Edge Cases
- Input series are expected to be date-valid, sortable, and semantically aligned with the request window.
- For insufficient observations or invalid denominator conditions, the engine returns deterministic error semantics (HTTP validation error and/or metric-level error details depending on endpoint contract).
- Where configured, policy controls (missing-data policy, fill method, reset rules, robustness policies) can materially change results and must be interpreted with diagnostics.`r`n`r`n## Worked Example
- `w_b=0.5`, local excess=0.5% => `0.25%`.



